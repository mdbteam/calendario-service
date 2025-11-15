# En app/main.py
from fastapi import FastAPI, Depends, HTTPException, status
from typing import List
from datetime import datetime, timedelta
import pyodbc
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db_connection
# ¡Importamos los modelos!
from app.models import (
    UserInDB, BloquePublico, CitaDetail,
    DisponibilidadPrivada,  # (Necesario para el endpoint 501)
    DisponibilidadCreate,  # (Necesario para el endpoint 501)
    CitaCreate
)
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


# --- ENDPOINTS DE DISPONIBILIDAD (¡PAUSADOS!) ---
# (Estos los dejamos así hasta que el frontend esté listo)

@app.post("/calendario/disponibilidad", status_code=status.HTTP_501_NOT_IMPLEMENTED, tags=["Calendario"])
def add_disponibilidad(
        disponibilidad: DisponibilidadCreate,
        current_user: UserInDB = Depends(get_current_active_user)
):
    """(PAUSADO) El frontend no soporta la creación de horarios aún."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Endpoint no habilitado.")


@app.get("/calendario/disponibilidad/me",
         response_model=List[DisponibilidadPrivada],
         tags=["Calendario"])
def get_my_availability(
        current_user: UserInDB = Depends(get_current_active_user)
):
    """(PAUSADO) El frontend no soporta la creación de horarios aún."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Endpoint no habilitado.")


# --- ENDPOINT PÚBLICO (¡EL BLINDADO!) ---

@app.get("/prestadores/{id_prestador}/disponibilidad",
         response_model=List[BloquePublico],
         tags=["Calendario"])
def get_public_availability(
        id_prestador: int,
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """
    (Req 2.0) Lógica Simplificada: Todo está "disponible"
    excepto las citas 'pendientes' y 'aceptadas'.
    """
    cursor = conn.cursor()
    bloques_publicos = []  # Lista de bloques "no disponible"

    try:
        # ¡ESTA ES LA LÓGICA CORRECTA!
        # NO consultamos Disponibilidad.
        # SOLO buscamos citas 'aceptada' y 'pendiente'.
        query_citas = """
            SELECT fecha_hora_cita, duracion_min FROM Citas 
            WHERE id_prestador = ? 
            AND estado IN ('aceptada', 'pendiente')
        """
        cursor.execute(query_citas, id_prestador)

        for row in cursor.fetchall():
            inicio_cita = row.fecha_hora_cita
            fin_cita = inicio_cita + timedelta(minutes=row.duracion_min)
            bloques_publicos.append(BloquePublico(
                hora_inicio=inicio_cita,
                hora_fin=fin_cita,
                estado="no disponible"
            ))

        # El frontend recibe SOLO los bloques "no disponible".
        # Es imposible que se superponga con un "disponible" del back.
        return bloques_publicos

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()


# --- ENDPOINTS DE CITAS (¡YA ESTÁN BLINDADOS!) ---

@app.post("/citas", status_code=status.HTTP_201_CREATED, tags=["Citas"])
def create_cita(
        cita_data: CitaCreate,
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Cliente) Solicita una nueva cita (estado 'pendiente')"""
    id_cliente = current_user.id_usuario
    if id_cliente == cita_data.id_prestador:
        raise HTTPException(status_code=400, detail="No puedes agendar una cita contigo mismo.")

    cursor = conn.cursor()
    try:
        # Validamos contra 'pendiente' y 'aceptada'
        cursor.execute(
            "SELECT COUNT(*) FROM Citas WHERE id_prestador = ? AND fecha_hora_cita = ? AND estado IN ('pendiente', 'aceptada')",
            cita_data.id_prestador, cita_data.fecha_hora_cita)
        if cursor.fetchone()[0] > 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="La hora de inicio seleccionada ya está ocupada.")

        # Insertamos con la duración
        cursor.execute(
            "INSERT INTO Citas (id_cliente, id_prestador, fecha_hora_cita, duracion_min, detalles, estado) VALUES (?, ?, ?, ?, ?, 'pendiente')",
            id_cliente, cita_data.id_prestador, cita_data.fecha_hora_cita, cita_data.duracion_min, cita_data.detalles)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al crear la cita: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Solicitud de cita enviada exitosamente."}


@app.get("/citas/me", response_model=List[CitaDetail], tags=["Citas"])
def get_my_citas(
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Req 2.2) Obtiene mis citas (como cliente o prestador) CON NOMBRES."""
    user_id = current_user.id_usuario
    cursor = conn.cursor()
    try:
        query = """
            SELECT 
                c.*,
                (cli.nombres + ' ' + cli.primer_apellido) AS cliente_nombres,
                (pre.nombres + ' ' + pre.primer_apellido) AS prestador_nombres
            FROM Citas c
            JOIN Usuarios cli ON c.id_cliente = cli.id_usuario
            JOIN Usuarios pre ON c.id_prestador = pre.id_usuario
            WHERE 
                c.id_cliente = ? OR c.id_prestador = ?
            ORDER BY c.fecha_hora_cita DESC
        """
        cursor.execute(query, user_id, user_id)
        rows = cursor.fetchall()
        if not rows:
            return []

        resultados = [CitaDetail.from_orm(row) for row in rows]
        return resultados

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()


@app.post("/citas/{id_cita}/aceptar", tags=["Citas"])
def confirm_cita(
        id_cita: int,
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Solo Prestadores) Confirma una solicitud de cita y crea el chat."""
    es_prestador(current_user)
    id_prestador = current_user.id_usuario
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE Citas SET estado = 'aceptada' WHERE id_cita = ? AND id_prestador = ? AND estado = 'pendiente'",
            id_cita, id_prestador)

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404,
                                detail="Cita no encontrada, ya fue procesada, o no tienes permiso.")

        cursor.execute("SELECT id_cliente FROM Citas WHERE id_cita = ?", id_cita)
        id_cliente = cursor.fetchone().id_cliente

        # Creamos la conversación (Asumiendo que la tabla Conversaciones existe)
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
def reject_cita(
        id_cita: int,
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Solo Prestadores) Rechaza Y ELIMINA una solicitud de cita."""
    es_prestador(current_user)
    id_prestador = current_user.id_usuario
    cursor = conn.cursor()
    try:
        # ¡Usamos DELETE para liberar el calendario!
        cursor.execute(
            "DELETE FROM Citas WHERE id_cita = ? AND id_prestador = ? AND estado = 'pendiente'",
            id_cita, id_prestador)

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404,
                                detail="Cita no encontrada, ya fue procesada, o no tienes permiso.")
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al rechazar la cita: {e}")
    finally:
        cursor.close()

    return {"mensaje": "Cita rechazada y eliminada. El calendario ha sido liberado."}


# --- ENDPOINTS DE CITAS (MODIFICADOS Y ARREGLADOS) ---

@app.post("/citas", status_code=status.HTTP_201_CREATED, tags=["Citas"])
def create_cita(
        cita_data: CitaCreate,  # <-- Modelo actualizado
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Cliente) Solicita una nueva cita (estado 'pendiente')"""
    id_cliente = current_user.id_usuario
    if id_cliente == cita_data.id_prestador:
        raise HTTPException(status_code=400, detail="No puedes agendar una cita contigo mismo.")

    cursor = conn.cursor()
    try:
        # (MEJORA) La validación de conflicto es más compleja ahora
        # (El frontend debería ayudar, pero aquí validamos de nuevo)
        # (Por ahora, mantenemos tu validación simple de la hora de INICIO)
        cursor.execute(
            "SELECT COUNT(*) FROM Citas WHERE id_prestador = ? AND fecha_hora_cita = ? AND estado IN ('pendiente', 'aceptada')",
            cita_data.id_prestador, cita_data.fecha_hora_cita)
        if cursor.fetchone()[0] > 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="La hora de inicio seleccionada ya está ocupada.")

        # ¡Insertamos con la duración!
        cursor.execute(
            "INSERT INTO Citas (id_cliente, id_prestador, fecha_hora_cita, duracion_min, detalles, estado) VALUES (?, ?, ?, ?, ?, 'pendiente')",
            id_cliente, cita_data.id_prestador, cita_data.fecha_hora_cita, cita_data.duracion_min, cita_data.detalles)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al crear la cita: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Solicitud de cita enviada exitosamente."}


@app.get("/citas/me", response_model=List[CitaDetail], tags=["Citas"])
def get_my_citas(
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Req 2.2) Obtiene mis citas (como cliente o prestador) CON NOMBRES."""
    user_id = current_user.id_usuario
    cursor = conn.cursor()
    try:
        # ¡La consulta con JOINs que necesita el frontend!
        query = """
            SELECT 
                c.*,
                (cli.nombres + ' ' + cli.primer_apellido) AS cliente_nombres,
                (pre.nombres + ' ' + pre.primer_apellido) AS prestador_nombres
            FROM Citas c
            JOIN Usuarios cli ON c.id_cliente = cli.id_usuario
            JOIN Usuarios pre ON c.id_prestador = pre.id_usuario
            WHERE 
                c.id_cliente = ? OR c.id_prestador = ?
            ORDER BY c.fecha_hora_cita DESC
        """
        cursor.execute(query, user_id, user_id)
        rows = cursor.fetchall()
        if not rows:
            return []

        # Mapeamos la respuesta al modelo Pydantic
        resultados = [CitaDetail.from_orm(row) for row in rows]
        return resultados

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()


# --- ENDPOINTS DE GESTIÓN (TUS ENDPOINTS ESTABAN BIEN, ¡LOS MANTENEMOS!) ---

@app.post("/citas/{id_cita}/confirmar", tags=["Citas"])
def confirm_cita(
        id_cita: int,
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Solo Prestadores) Confirma una solicitud de cita y crea el chat."""
    es_prestador(current_user)
    id_prestador = current_user.id_usuario
    cursor = conn.cursor()
    try:
        # 1. Actualizamos la cita
        cursor.execute(
            "UPDATE Citas SET estado = 'aceptada' WHERE id_cita = ? AND id_prestador = ? AND estado = 'pendiente'",
            id_cita, id_prestador)

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404,
                                detail="Cita no encontrada, ya fue procesada, o no tienes permiso.")

        # 2. Obtenemos el ID del cliente
        cursor.execute("SELECT id_cliente FROM Citas WHERE id_cita = ?", id_cita)
        id_cliente = cursor.fetchone().id_cliente

        # 3. Creamos la conversación (Tu lógica MERGE era perfecta)
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
def reject_cita(
        id_cita: int,
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    """(Solo Prestadores) Rechaza una solicitud de cita."""
    es_prestador(current_user)
    id_prestador = current_user.id_usuario
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE Citas SET estado = 'rechazada' WHERE id_cita = ? AND id_prestador = ? AND estado = 'pendiente'",
            id_cita, id_prestador)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404,
                                detail="Cita no encontrada, ya fue procesada, o no tienes permiso.")
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al rechazar la cita: {e}")
    finally:
        cursor.close()

    return {"mensaje": "Cita rechazada exitosamente."}