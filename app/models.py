# app/models.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional

# --- (Modelos anteriores sin cambios) ---
class DisponibilidadCreate(BaseModel):
    fecha_hora_inicio: datetime
    fecha_hora_fin: datetime

class HorarioDisponible(BaseModel):
    hora_inicio: datetime

class CitaCreate(BaseModel):
    id_prestador: int
    fecha_hora_cita: datetime
    detalles: Optional[str] = None

class UserInDB(BaseModel):
    id_usuario: int
    id_rol: int
    estado: str

# --- NUEVO MODELO ---
class CitaDetail(BaseModel):
    id_cita: int
    id_cliente: int
    id_prestador: int
    fecha_hora_cita: datetime
    detalles: Optional[str] = None
    estado: str