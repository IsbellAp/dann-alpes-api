@app.post("/resenas")
def crear_resena(body: dict):
    existente = resenas_col.find_one({
        "id_reserva": body["id_reserva"],
        "estado": "PUBLICADA"    # ← mayúsculas
    })
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe una reseña activa para esta reserva")
    nueva = {
        "id_hotel":            body["id_hotel"],
        "documento_cliente":   body["documento_cliente"],
        "id_reserva":          body["id_reserva"],
        "puntuacion_estrellas": body["puntuacion_estrellas"],
        "descripcion":         body["descripcion"],
        "fecha":               datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "estado":              "PUBLICADA",    # ← mayúsculas
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
        {"id_hotel": id_hotel, "estado": "PUBLICADA"},    # ← mayúsculas
        sort=[(orden_campo, -1)]
    ))
    return [fix_id(d) for d in docs]

@app.get("/resenas/cliente/{documento_cliente}")
def get_resenas_cliente(documento_cliente: int, orden: str = "fecha"):
    orden_campo = "fecha" if orden == "fecha" else "id_hotel"
    docs = list(resenas_col.find(
        {"documento_cliente": documento_cliente},
        sort=[(orden_campo, -1)]
    ))
    return [fix_id(d) for d in docs]

@app.delete("/resenas/{id}")
def eliminar_resena(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "estado":             "ELIMINADA",    # ← mayúsculas
            "eliminada_por":      "cliente",
            "motivo_eliminacion": "Eliminada por el cliente"
        }}
    )
    return {"mensaje": "Reseña eliminada"}

@app.delete("/resenas/{id}/admin")
def eliminar_resena_admin(id: str):
    resenas_col.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "estado":             "ELIMINADA",    # ← mayúsculas
            "eliminada_por":      "admin",
            "motivo_eliminacion": "Eliminada por administrador"
        }}
    )
    return {"mensaje": "Reseña eliminada por administrador"}

@app.get("/analytics/top-hoteles")
def top_hoteles(fecha_inicio: str, fecha_fin: str):
    pipeline = [
        {"$match": {
            "estado": "PUBLICADA",    # ← mayúsculas
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
            "estado": "PUBLICADA",    # ← mayúsculas
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
            "estado": "PUBLICADA"    # ← mayúsculas
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
