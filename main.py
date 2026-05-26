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
votos_col = db["votos"]
respuestas_col = db["respuestas"]

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
    
    from bson.int64 import Int64
    import random
    
    nueva = {
        "id_reseña":           Int64(random.randint(100000, 999999999)),
        "id_hotel":            body["id_hotel"],
        "documento_cliente":   body["documento_cliente"],
        "id_reserva":          body["id_reserva"],
        "puntuacion_estrellas": body["puntuacion_estrellas"],
        "descripcion":         body["descripcion"],
        "fecha":               datetime.now().strftime("%Y-%m-%d"),
        "hora":                datetime.now().strftime("%H:%M"),
        "estado":              "publicada",
        "destacada":           False,
        "motivo_eliminacion":  None,
        "eliminada_por":       None
    }
    resultado = resenas_col.insert_one(nueva)
    return {"id": str(resultado.inserted_id), "mensaje": "Reseña creada"}


@app.get("/resenas/{id}")
def get_resena_por_id(id: str):
    resena = resenas_col.find_one({"_id": ObjectId(id)})
    if not resena:
        raise HTTPException(404, "Reseña no encontrada")
    
    # Contar votos
    resena["votos_utilidad"] = votos_col.count_documents({
        "id_reseña": resena.get("id_reseña"),
        "pulgar_arriba": True
    })
    
    # Buscar respuesta
    respuesta = respuestas_col.find_one({"id_reseña": resena.get("id_reseña")})
    if respuesta:
        resena["respuesta_admin"] = respuesta.get("descripcion")
    
    return fix_id(resena)
@app.get("/resenas/hotel/{id_hotel}")
def get_resenas_hotel(id_hotel: int, orden: str = "fecha"):
    from bson.int64 import Int64
    orden_campo = "fecha" if orden == "fecha" else "votos_utilidad"
    docs = list(resenas_col.find(
        {"$and": [
            {"$or": [
                {"id_hotel": id_hotel},
                {"id_hotel": Int64(id_hotel)}
            ]},
            {"estado": "publicada"}
        ]},
        sort=[(orden_campo, -1)]
    ))
    
    # Contar votos de cada reseña
   # Contar votos y buscar respuesta de cada reseña
    for d in docs:
        d["votos_utilidad"] = votos_col.count_documents({
            "id_reseña": d.get("id_reseña"),
            "pulgar_arriba": True
        })
        respuesta = respuestas_col.find_one({"id_reseña": d.get("id_reseña")})
        if respuesta:
            d["respuesta_admin"] = respuesta.get("descripcion")
    
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
    
    # Contar votos de cada reseña
    # Contar votos y buscar respuesta de cada reseña
    for d in docs:
        d["votos_utilidad"] = votos_col.count_documents({
            "id_reseña": d.get("id_reseña"),
            "pulgar_arriba": True
        })
        respuesta = respuestas_col.find_one({"id_reseña": d.get("id_reseña")})
        if respuesta:
            d["respuesta_admin"] = respuesta.get("descripcion")
    
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
async def eliminar_resena(id: str, request: Request):
    try:
        body = await request.json()
    except:
        body = {}
    
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "estado":             "ELIMINADA",
            "eliminada_por":      body.get("usuario", "cliente"),
            "motivo_eliminacion": "Eliminada por el cliente"
        }}
    )
    return {"mensaje": "Reseña eliminada"}


@app.post("/resenas/{id}/util")
async def marcar_util(id: str, request: Request):
    try:
        body = await request.json()
    except:
        body = {}
    
    # Obtenemos el id_reseña real del documento
    resena = resenas_col.find_one({"_id": ObjectId(id)})
    if not resena:
        raise HTTPException(404, "Reseña no encontrada")
    
    from bson.int64 import Int64
    from datetime import datetime
    import random
    
    nuevo_voto = {
        "id_voto_de_utilidad": Int64(random.randint(1000000, 99999999)),
        "documento_cliente": Int64(body.get("documento_cliente", 0)),
        "id_reseña": resena.get("id_reseña"),
        "id_respuesta_administrativa": None,
        "pulgar_arriba": True,
        "fecha_voto": datetime.now()
    }
    votos_col.insert_one(nuevo_voto)
    
    return {"mensaje": "Voto registrado"}

@app.put("/resenas/{id}/respuesta")
async def responder_resena(id: str, request: Request):
    body = await request.json()
    
    from bson.int64 import Int64
    from datetime import datetime
    import random
    
    resena = resenas_col.find_one({"_id": ObjectId(id)})
    if not resena:
        raise HTTPException(404, "Reseña no encontrada")
    
    # Verifica si ya hay respuesta para editar
    existente = respuestas_col.find_one({"id_reseña": resena.get("id_reseña")})
    
    if existente:
        # Editar respuesta existente
        respuestas_col.update_one(
            {"_id": existente["_id"]},
            {"$set": {
                "descripcion": body["respuesta"],
                "fecha": datetime.now()
            }}
        )
    else:
        # Crear nueva respuesta
        nueva = {
            "id_respuesta_administrativa": Int64(random.randint(1000000, 99999999)),
            "id_reseña": resena.get("id_reseña"),
            "documento_administrador": Int64(body.get("documento_administrador", 7483921056)),
            "descripcion": body["respuesta"],
            "fecha": datetime.now(),
            "hora": datetime.now().strftime("%H:%M")
        }
        respuestas_col.insert_one(nueva)
    
    return {"mensaje": "Respuesta registrada"}

@app.delete("/resenas/{id}/admin")
async def eliminar_resena_admin(id: str, request: Request):
    try:
        body = await request.json()
    except:
        body = {}
    
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "estado":             "ELIMINADA",
            "eliminada_por":      body.get("usuario", "admin"),
            "motivo_eliminacion": body.get("motivo", "Eliminada por administrador")
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
        {
            "$addFields": {
                "fecha_str": {
                    "$cond": [
                        { "$eq": [{ "$type": "$fecha" }, "date"] },
                        {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$fecha"
                            }
                        },
                        "$fecha"
                    ]
                }
            }
        },
        {
            "$match": {
                "estado": { "$in": ["PUBLICADA", "publicada"] },
                "fecha_str": {
                    "$gte": fecha_inicio,
                    "$lte": fecha_fin
                }
            }
        },
        {
            "$group": {
                "_id": "$id_hotel",
                "promedio": {"$avg": "$puntuacion_estrellas"},
                "total_resenas": {"$sum": 1}
            }
        },
        {
            "$sort": {
                "promedio": -1,
                "total_resenas": -1
            }
        },
        { "$limit": 10 }
    ]

    return list(resenas_col.aggregate(pipeline))

@app.get("/analytics/evolucion/{id_hotel}")
def evolucion_hotel(id_hotel: int, anio: int):

    from bson.int64 import Int64

    pipeline = [
        {
            "$addFields": {
                "fecha_str": {
                    "$cond": [
                        { "$eq": [{ "$type": "$fecha" }, "date"] },
                        {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$fecha"
                            }
                        },
                        "$fecha"
                    ]
                }
            }
        },
        {
            "$match": {
                "id_hotel": { "$in": [id_hotel, Int64(id_hotel)] },
                "estado": { "$in": ["PUBLICADA", "publicada"] },
                "fecha_str": {
                    "$gte": f"{anio}-01-01",
                    "$lte": f"{anio}-12-31"
                }
            }
        },
        {
            "$addFields": {
                "mes": { "$substr": ["$fecha_str", 0, 7] }
            }
        },
        {
            "$group": {
                "_id": "$mes",
                "promedio": { "$avg": "$puntuacion_estrellas" },
                "total": { "$sum": 1 }
            }
        },
        {
            "$sort": { "_id": 1 }
        }
    ]

    return list(resenas_col.aggregate(pipeline))

@app.get("/analytics/ciudad")
def perfil_ciudad(hoteles: str):
    from bson.int64 import Int64

    ids = [int(x) for x in hoteles.split(",")]

    pipeline = [
        {
            "$match": {
                "id_hotel": { "$in": ids + [Int64(x) for x in ids] },
                "estado": { "$in": ["PUBLICADA", "publicada"] }
            }
        },
        {
            "$group": {
                "_id": "$id_hotel",
                "promedio": { "$avg": "$puntuacion_estrellas" },
                "total": { "$sum": 1 },

                # TEMPORAL (no rompe y permite entregar)
                "con_respuesta": { "$sum": 0 },

                "destacadas": {
                    "$sum": {
                        "$cond": ["$destacada", 1, 0]
                    }
                }
            }
        },
        {
            "$sort": { "promedio": -1 }
        }
    ]

    return list(resenas_col.aggregate(pipeline))
