from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conexión a MongoDB Atlas
MONGO_URL = os.environ.get("MONGO_URL")
client = MongoClient(MONGO_URL)
db = client["dann_alpes_resenas"]
resenas_col = db["resenas"]

def fix_id(doc):
    doc["_id"] = str(doc["_id"])
    return doc

# ─── RF1: Crear reseña ───────────────────────────────────────
@app.post("/resenas")
def crear_resena(body: dict):
    # Verificar que no existe reseña previa para esa reserva
    existente = resenas_col.find_one({
        "id_reserva": body["id_reserva"],
        "estado": "publicada"
    })
    if existente:
        raise HTTPException(400, "Ya existe una reseña para esta reserva")
    
    nueva = {
        "id_hotel": body["id_hotel"],
        "id_cliente": body["id_cliente"],
        "id_reserva": body["id_reserva"],
        "calificacion": body["calificacion"],
        "texto": body["texto"],
        "fecha_creacion": datetime.now().strftime("%Y-%m-%d"),
        "estado": "publicada",
        "destacada": False,
        "votos_utilidad": 0,
        "respuesta_admin": None
    }
    resultado = resenas_col.insert_one(nueva)
    return {"id": str(resultado.inserted_id), "mensaje": "Reseña creada"}

# ─── RF2: Editar reseña ──────────────────────────────────────
@app.put("/resenas/{id}")
def editar_resena(id: str, body: dict):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "calificacion": body["calificacion"],
            "texto": body["texto"]
        }}
    )
    return {"mensaje": "Reseña actualizada"}

# ─── RF3: Eliminar reseña (cliente) ─────────────────────────
@app.delete("/resenas/{id}")
def eliminar_resena(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"estado": "eliminada"}}
    )
    return {"mensaje": "Reseña eliminada"}

# ─── RF4: Consultar reseñas de un hotel ─────────────────────
@app.get("/resenas/hotel/{id_hotel}")
def get_resenas_hotel(id_hotel: int, orden: str = "fecha"):
    orden_campo = "fecha_creacion" if orden == "fecha" else "votos_utilidad"
    docs = list(resenas_col.find(
        {"id_hotel": id_hotel, "estado": "publicada"},
        sort=[(orden_campo, -1)]
    ))
    return [fix_id(d) for d in docs]

# ─── RF5: Marcar reseña como útil ───────────────────────────
@app.post("/resenas/{id}/util")
def marcar_util(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$inc": {"votos_utilidad": 1}}
    )
    return {"mensaje": "Voto registrado"}

# ─── RF6: Historial de reseñas del cliente ──────────────────
@app.get("/resenas/cliente/{id_cliente}")
def get_resenas_cliente(id_cliente: int, orden: str = "fecha"):
    orden_campo = "fecha_creacion" if orden == "fecha" else "id_hotel"
    docs = list(resenas_col.find(
        {"id_cliente": id_cliente},
        sort=[(orden_campo, -1)]
    ))
    return [fix_id(d) for d in docs]

# ─── RF7: Responder reseña (admin) ──────────────────────────
@app.put("/resenas/{id}/respuesta")
def responder_resena(id: str, body: dict):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"respuesta_admin": body["respuesta"]}}
    )
    return {"mensaje": "Respuesta registrada"}

# ─── RF8: Eliminar reseña (admin) ───────────────────────────
@app.delete("/resenas/{id}/admin")
def eliminar_resena_admin(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"estado": "eliminada"}}
    )
    return {"mensaje": "Reseña eliminada por administrador"}

# ─── RF9: Destacar reseña ───────────────────────────────────
@app.post("/resenas/{id}/destacar")
def destacar_resena(id: str, body: dict):
    # Quitar destacado anterior del mismo hotel
    resenas_col.update_many(
        {"id_hotel": body["id_hotel"]},
        {"$set": {"destacada": False}}
    )
    # Destacar la nueva
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"destacada": True}}
    )
    return {"mensaje": "Reseña destacada"}

# ─── RFC1: Top 10 hoteles por calificación ──────────────────
@app.get("/analytics/top-hoteles")
def top_hoteles(fecha_inicio: str, fecha_fin: str):
    pipeline = [
        {"$match": {
            "estado": "publicada",
            "fecha_creacion": {"$gte": fecha_inicio, "$lte": fecha_fin}
        }},
        {"$group": {
            "_id": "$id_hotel",
            "promedio": {"$avg": "$calificacion"},
            "total_resenas": {"$sum": 1}
        }},
        {"$sort": {"promedio": -1}},
        {"$limit": 10}
    ]
    return list(resenas_col.aggregate(pipeline))

# ─── RFC2: Evolución reputación de un hotel ─────────────────
@app.get("/analytics/evolucion/{id_hotel}")
def evolucion_hotel(id_hotel: int, anio: int):
    pipeline = [
        {"$match": {
            "id_hotel": id_hotel,
            "estado": "publicada",
            "fecha_creacion": {
                "$gte": f"{anio}-01-01",
                "$lte": f"{anio}-12-31"
            }
        }},
        {"$group": {
            "_id": {"$substr": ["$fecha_creacion", 0, 7]},
            "promedio": {"$avg": "$calificacion"},
            "total": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    return list(resenas_col.aggregate(pipeline))

# ─── RFC3: Perfil comparativo hoteles por ciudad ────────────
@app.get("/analytics/ciudad/{id_ciudad}")
def perfil_ciudad(id_ciudad: int, hoteles: str):
    ids = [int(x) for x in hoteles.split(",")]
    pipeline = [
        {"$match": {
            "id_hotel": {"$in": ids},
            "estado": "publicada"
        }},
        {"$group": {
            "_id": "$id_hotel",
            "promedio": {"$avg": "$calificacion"},
            "total": {"$sum": 1},
            "con_respuesta": {
                "$sum": {
                    "$cond": [
                        {"$ne": ["$respuesta_admin", None]}, 1, 0
                    ]
                }
            },
            "destacadas": {
                "$sum": {"$cond": ["$destacada", 1, 0]}
            }
        }}
    ]
    return list(resenas_col.aggregate(pipeline))
