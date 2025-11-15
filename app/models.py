# En app/models.py
from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import List, Optional


# --- Modelo base para la Autenticación ---
class UserInDB(BaseModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    correo: str
    id_rol: int
    estado: str

    class Config:
        from_attributes = True # <-- CORREGIDO (Era orm_mode)


# --- REQ 2.0 (El que reemplaza a HorarioDisponible) ---
class BloquePublico(BaseModel):
    hora_inicio: datetime
    hora_fin: datetime
    estado: str # "disponible" | "no disponible"


# --- REQ 2.1 (Para el Prestador) ---
class DisponibilidadPrivada(BaseModel):
    id_disponibilidad: int
    hora_inicio: datetime
    hora_fin: datetime
    es_bloqueo: bool

    class Config:
        from_attributes = True

# --- REQ 2.2 (Mis Citas - CORREGIDO) ---
class CitaDetail(BaseModel):
    id_cita: int
    id_cliente: int
    id_prestador: int
    fecha_hora_cita: datetime
    duracion_min: int
    detalles: Optional[str] = None
    estado: str
    id_trabajo: Optional[int]
    id_valoracion: Optional[int]
    cliente_nombres: str
    prestador_nombres: str

    class Config:
        from_attributes = True
# --- MODELOS DE ENTRADA (CREATE) ---

# (Prestador) Define su horario (si trabaja o bloquea)
class DisponibilidadCreate(BaseModel):
    hora_inicio: datetime
    hora_fin: datetime
    es_bloqueo: bool = Field(False, description="False=Disponible, True=No disponible")


# (Cliente) Solicita una cita
class CitaCreate(BaseModel):
    id_prestador: int
    fecha_hora_cita: datetime
    duracion_min: int = Field(60, description="Duración en minutos")  # <-- AÑADIDO
    detalles: Optional[str] = None