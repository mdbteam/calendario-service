# app/main.py
from fastapi import FastAPI, Depends, HTTPException, status
from typing import List
from datetime import datetime, timedelta
import pyodbc
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db_connection
from app.models import DisponibilidadCreate, HorarioDisponible, CitaCreate, UserInDB, CitaDetail
from app.auth_utils import get_current_active_user

app = FastAPI(
    title="Servicio de Calendario - Chambee",
    description="Gestiona la disponibilidad y citas de los prestadores.",
    version="1.0.0"
)


def es_prestador(user: UserInDB):
    if user.id_rol not in [2, 3]:  # 2=Proveedor, 3=Híbrido
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Esta acción solo puede ser realizada por un prestador de servicios.")


@app.get("/", tags=["Status"])
def root():
    return {"message": "Calendar Service funcionando 🚀"}


# --- (Endpoints /disponibilidad y /citas sin cambios) ---
@app.post("/disponibilidad", status_code=status.HTTP_201_CREATED, tags=["Disponibilidad"])
def add_disponibilidad(disponibilidad: DisponibilidadCreate, current_user: UserInDB = Depends(get_current_active_user),
                       conn: pyodbc.Connection = Depends(get_db_connection)):
    es_prestador(current_user)
    id_prestador = current_user.id_usuario
    if disponibilidad.fecha_hora_fin <= disponibilidad.fecha_hora_inicio:
        raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la de inicio.")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO Disponibilidad (id_prestador, fecha_hora_inicio, fecha_hora_fin) VALUES (?, ?, ?)",
                       id_prestador, disponibilidad.fecha_hora_inicio, disponibilidad.fecha_hora_fin)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al guardar: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Bloque de disponibilidad añadido."}


@app.get("/prestadores/{id_prestador}/disponibilidad", response_model=List[HorarioDisponible], tags=["Disponibilidad"])
def get_disponibilidad(id_prestador: int, conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    ahora = datetime.now()
    cursor.execute("SELECT fecha_hora_inicio, fecha_hora_fin FROM Disponibilidad WHERE id_prestador = ?", id_prestador)
    bloques_disponibles = cursor.fetchall()
    cursor.execute(
        "SELECT fecha_hora_cita FROM Citas WHERE id_prestador = ? AND estado IN ('solicitada', 'confirmada')",
        id_prestador)
    citas_agendadas = {row.fecha_hora_cita for row in cursor.fetchall()}
    cursor.close()
    horas_finales = set()
    for bloque in bloques_disponibles:
        hora_actual = bloque.fecha_hora_inicio
        while hora_actual < bloque.fecha_hora_fin:
            if hora_actual > ahora and hora_actual not in citas_agendadas:
                horas_finales.add(hora_actual)
            hora_actual += timedelta(hours=1)
    horas_ordenadas = sorted(list(horas_finales))
    return [HorarioDisponible(hora_inicio=h) for h in horas_ordenadas]


@app.post("/citas", status_code=status.HTTP_201_CREATED, tags=["Citas"])
def create_cita(cita_data: CitaCreate, current_user: UserInDB = Depends(get_current_active_user),
                conn: pyodbc.Connection = Depends(get_db_connection)):
    id_cliente = current_user.id_usuario
    if id_cliente == cita_data.id_prestador:
        raise HTTPException(status_code=400, detail="No puedes agendar una cita contigo mismo.")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM Citas WHERE id_prestador = ? AND fecha_hora_cita = ? AND estado IN ('solicitada', 'confirmada')",
            cita_data.id_prestador, cita_data.fecha_hora_cita)
        if cursor.fetchone()[0] > 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="La hora seleccionada ya no está disponible.")
        cursor.execute(
            "INSERT INTO Citas (id_cliente, id_prestador, fecha_hora_cita, detalles, estado) VALUES (?, ?, ?, ?, 'solicitada')",
            id_cliente, cita_data.id_prestador, cita_data.fecha_hora_cita, cita_data.detalles)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al crear la cita: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Solicitud de cita enviada exitosamente."}


# --- NUEVOS ENDPOINTS ---

@app.get("/citas/me", response_model=List[CitaDetail], tags=["Citas"])
def get_my_citas(current_user: UserInDB = Depends(get_current_active_user),
                 conn: pyodbc.Connection = Depends(get_db_connection)):
    """Obtiene todas las citas (como cliente o prestador) del usuario autenticado."""
    user_id = current_user.id_usuario
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Citas WHERE id_cliente = ? OR id_prestador = ?", user_id, user_id)
    citas_db = cursor.fetchall()
    cursor.close()

    citas = [CitaDetail(**dict(zip([column[0] for column in row.cursor_description], row))) for row in citas_db]
    return citas


@app.post("/citas/{id_cita}/confirmar", tags=["Citas"])
def confirm_cita(id_cita: int, current_user: UserInDB = Depends(get_current_active_user),
                 conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Solo Prestadores) Confirma una solicitud de cita."""
    es_prestador(current_user)
    id_prestador = current_user.id_usuario
    cursor = conn.cursor()
    try:
        # 1. Actualizamos la cita a 'confirmada', asegurándonos de que el prestador es el dueño
        cursor.execute(
            "UPDATE Citas SET estado = 'confirmada' WHERE id_cita = ? AND id_prestador = ? AND estado = 'solicitada'",
            id_cita, id_prestador)

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404,
                                detail="Cita no encontrada, ya fue procesada, o no tienes permiso para confirmarla.")

        # 2. Obtenemos el ID del cliente para crear la conversación
        cursor.execute("SELECT id_cliente FROM Citas WHERE id_cita = ?", id_cita)
        id_cliente = cursor.fetchone().id_cliente

        # 3. Creamos la conversación en la tabla Conversaciones
        # Usamos MERGE para evitar duplicados si la conversación ya existía por algún motivo
        cursor.execute(
            """
            MERGE Conversaciones AS target
            USING (SELECT ? AS id_usuario_1, ? AS id_usuario_2) AS source
            ON (target.id_usuario_1 = source.id_usuario_1 AND target.id_usuario_2 = source.id_usuario_2)
            OR (target.id_usuario_1 = source.id_usuario_2 AND target.id_usuario_2 = source.id_usuario_1)
            WHEN NOT MATCHED THEN
                INSERT (id_usuario_1, id_usuario_2) VALUES (source.id_usuario_1, source.id_usuario_2);
            """,
            min(id_prestador, id_cliente), max(id_prestador, id_cliente)
        )

        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al confirmar la cita: {e}")
    finally:
        cursor.close()

    return {"mensaje": "Cita confirmada exitosamente. El chat ha sido activado."}


@app.post("/citas/{id_cita}/rechazar", tags=["Citas"])
def reject_cita(id_cita: int, current_user: UserInDB = Depends(get_current_active_user),
                conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Solo Prestadores) Rechaza una solicitud de cita."""
    es_prestador(current_user)
    id_prestador = current_user.id_usuario
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE Citas SET estado = 'rechazada' WHERE id_cita = ? AND id_prestador = ? AND estado = 'solicitada'",
            id_cita, id_prestador)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404,
                                detail="Cita no encontrada, ya fue procesada, o no tienes permiso para rechazarla.")
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al rechazar la cita: {e}")
    finally:
        cursor.close()

    return {"mensaje": "Cita rechazada exitosamente."}