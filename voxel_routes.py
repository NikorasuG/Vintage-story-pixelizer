"""Page « STL → voxels » : à enregistrer dans app.py avec `app.register_blueprint(bp)`."""
import base64

import numpy as np
from flask import Blueprint, jsonify, render_template, request

import voxel

bp = Blueprint("voxel", __name__)

TAILLE_UPLOAD_MAX = 50 * 1024 * 1024   # un STL binaire de 1 M de triangles pèse environ 50 Mo


@bp.record_once
def _configurer(etat):
    # les fichiers STL sont plus gros que les images : on relève la limite globale si besoin
    actuel = etat.app.config.get("MAX_CONTENT_LENGTH") or 0
    etat.app.config["MAX_CONTENT_LENGTH"] = max(actuel, TAILLE_UPLOAD_MAX)


@bp.get("/voxel")
def page():
    return render_template("voxel.html", hauteur_max=voxel.HAUTEUR_MAX)


@bp.post("/api/voxelize")
def api_voxelize():
    fichier = request.files.get("stl")
    if not fichier:
        return jsonify(error="Aucun fichier STL reçu"), 400
    try:
        hauteur = int(request.form.get("hauteur", 64))
    except ValueError:
        return jsonify(error="Hauteur invalide"), 400
    axe = request.form.get("axe", "z")
    if axe not in ("x", "y", "z"):
        axe = "z"

    try:
        triangles = voxel.lire_stl(fichier.read())
        grille, infos, avertissement = voxel.voxeliser(triangles, hauteur, axe)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    # grille (couche, y, x) aplatie puis compactée : 1 bit par voxel
    bits = base64.b64encode(np.packbits(grille.ravel()).tobytes()).decode()
    return jsonify(**infos, avertissement=avertissement, bits=bits)
