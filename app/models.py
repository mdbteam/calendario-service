# app/models.py
from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import List, Optional

# Modelo para que el prestador envíe su disponibilidad
class DisponibilidadCreate(BaseModel):
    fecha_hora_inicio: datetime
    fecha_hora_fin: datetime

# Modelo para mostrar cada hora disponible al cliente
class HorarioDisponible(BaseModel):
    hora_inicio: datetime

# Modelo para que el cliente solicite una cita
class CitaCreate(BaseModel):
    id_prestador: int
    fecha_hora_cita: datetime
    detalles: Optional[str] = None

# --- MODELO CORREGIDO Y COMPLEto ---
# Modelo interno para el usuario autenticado
class UserInDB(BaseModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    correo: str
    id_rol: int
    estado: str

# Modelo para la respuesta de "Mis Citas"
class CitaDetail(BaseModel):
    id_cita: int
    id_cliente: int
    id_prestador: int
    fecha_hora_cita: datetime
    detalles: Optional[str] = None
    estado: str