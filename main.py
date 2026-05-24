from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import os

app = FastAPI()

# Responder OPTIONS manualmente para todos los endpoints
@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    return Response(
        content="",
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "3600",
        }
    )

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


MONGO_URL = os.environ.get("MONGO_URL")
client = MongoClient(MONGO_URL)
db = client["dann_alpes_resenas"]
resenas_col = db["resenas"]

def fix_id(doc):
    doc["_id"] = str(doc["_id"])
    return doc

@app.post("/resenas")
def crear_resena(body: dict):
    existente = resenas_col.find_one({
        "id_reserva": body["id_reserva"],
        "estado": "publicada"
    })
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe una reseña activa para esta reserva")
    nueva = {
        "id_hotel":            body["id_hotel"],
        "documento_cliente":   body["documento_cliente"],
        "id_reserva":          body["id_reserva"],
        "puntuacion_estrellas": body["puntuacion_estrellas"],
        "descripcion":         body["descripcion"],
        "fecha":               datetime.now().strftime("%Y-%m-%d"),
        "estado":              "PUBLICADA",
        "destacada":           False,
        "votos_utilidad":      0,
        "respuesta_admin":     None,
        "motivo_eliminacion":  None,
        "eliminada_por":       None
    }
    resultado = resenas_col.insert_one(nueva)
    return {"id": str(resultado.inserted_id), "mensaje": "Reseña creada"}

@app.get("/resenas/hotel/{id_hotel}")
def get_resenas_hotel(id_hotel: int, orden: str = "fecha"):
    orden_campo = "fecha" if orden == "fecha" else "votos_utilidad"
    docs = list(resenas_col.find(
        {"id_hotel": id_hotel, "estado": "PUBLICADA"},
        sort=[(orden_campo, -1)]
    ))
    return [fix_id(d) for d in docs]

@app.get("/resenas/cliente/{documento_cliente}")
def get_resenas_cliente(documento_cliente: int, orden: str = "fecha"):
    from bson.int64 import Int64
    orden_campo = "fecha" if orden == "fecha" else "id_hotel"
    docs = list(resenas_col.find(
        {"$or": [
            {"documento_cliente": documento_cliente},
            {"documento_cliente": Int64(documento_cliente)}
        ]},
        sort=[(orden_campo, -1)]
    ))
    return [fix_id(d) for d in docs]

@app.put("/resenas/{id}")
def editar_resena(id: str, body: dict):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "puntuacion_estrellas": body["puntuacion_estrellas"],
            "descripcion":          body["descripcion"]
        }}
    )
    return {"mensaje": "Reseña actualizada"}

@app.delete("/resenas/{id}")
def eliminar_resena(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "estado":             "ELIMINADA",
            "eliminada_por":      "cliente",
            "motivo_eliminacion": "Eliminada por el cliente"
        }}
    )
    return {"mensaje": "Reseña eliminada"}

@app.post("/resenas/{id}/util")
def marcar_util(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$inc": {"votos_utilidad": 1}}
    )
    return {"mensaje": "Voto registrado"}

@app.put("/resenas/{id}/respuesta")
def responder_resena(id: str, body: dict):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"respuesta_admin": body["respuesta"]}}
    )
    return {"mensaje": "Respuesta registrada"}

@app.delete("/resenas/{id}/admin")
def eliminar_resena_admin(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "estado":             "ELIMINADA",
            "eliminada_por":      "admin",
            "motivo_eliminacion": "Eliminada por administrador"
        }}
    )
    return {"mensaje": "Reseña eliminada por administrador"}

@app.post("/resenas/{id}/destacar")
def destacar_resena(id: str, body: dict):
    resenas_col.update_many(
        {"id_hotel": body["id_hotel"]},
        {"$set": {"destacada": False}}
    )
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"destacada": True}}
    )
    return {"mensaje": "Reseña destacada"}

@app.get("/analytics/top-hoteles")
def top_hoteles(fecha_inicio: str, fecha_fin: str):
    pipeline = [
        {"$match": {
            "estado": "publicada",
            "fecha": {"$gte": fecha_inicio, "$lte": fecha_fin}
        }},
        {"$group": {
            "_id": "$id_hotel",
            "promedio": {"$avg": "$puntuacion_estrellas"},
            "total_resenas": {"$sum": 1}
        }},
        {"$sort": {"promedio": -1}},
        {"$limit": 10}
    ]
    return list(resenas_col.aggregate(pipeline))

@app.get("/analytics/evolucion/{id_hotel}")
def evolucion_hotel(id_hotel: int, anio: int):
    pipeline = [
        {"$match": {
            "id_hotel": id_hotel,
            "estado": "PUBLICADA",
            "fecha": {
                "$gte": f"{anio}-01-01",
                "$lte": f"{anio}-12-31"
            }
        }},
        {"$group": {
            "_id": {"$substr": ["$fecha", 0, 7]},
            "promedio": {"$avg": "$puntuacion_estrellas"},
            "total": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    return list(resenas_col.aggregate(pipeline))

@app.get("/analytics/ciudad")
def perfil_ciudad(hoteles: str):
    ids = [int(x) for x in hoteles.split(",")]
    pipeline = [
        {"$match": {
            "id_hotel": {"$in": ids},
            "estado": "PUBLICADA"
        }},
        {"$group": {
            "_id": "$id_hotel",
            "promedio": {"$avg": "$puntuacion_estrellas"},
            "total": {"$sum": 1},
            "con_respuesta": {
                "$sum": {
                    "$cond": [{"$ne": ["$respuesta_admin", None]}, 1, 0]
                }
            },
            "destacadas": {
                "$sum": {"$cond": ["$destacada", 1, 0]}
            }
        }}
    ]
    return list(resenas_col.aggregate(pipeline))
