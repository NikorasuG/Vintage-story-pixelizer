import base64
import io

from flask import Flask, jsonify, render_template, request

from voxel_routes import bp as voxel_bp

import core

MAX_GRILLE_CASES = 250_000   # au-delà, la grille numérotée n'est pas dessinée (image trop lourde)
TAILLE_PIXEL_MAX = 64

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024  # 20 Mo
app.register_blueprint(voxel_bp)

@app.get("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "icons/favicon.ico",
                               mimetype="image/vnd.microsoft.icon")

def erreur(message, code=400):
    return jsonify(error=message), code


@app.errorhandler(413)
def trop_gros(_):
    return erreur("Fichier trop volumineux (maximum 20 Mo)", 413)


def png_base64(img):
    tampon = io.BytesIO()
    img.save(tampon, format="PNG")
    return base64.b64encode(tampon.getvalue()).decode()


@app.get("/")
def index():
    return render_template("index.html", palette=core.PALETTE_HEX,
                           max_dim=core.MAX_DIM, taille_pixel_max=TAILLE_PIXEL_MAX,
                           grille_max=MAX_GRILLE_CASES)


@app.post("/api/generate")
def api_generate():
    fichier = request.files.get("image")
    if not fichier:
        return erreur("Aucune image reçue")
    try:
        img = core.charger_image(fichier.stream)
    except Exception:
        return erreur("Image illisible ou trop grande")

    try:
        taille_case = max(16, min(60, int(request.form.get("taille_case", 28))))
        taille_pixel = max(1, min(TAILLE_PIXEL_MAX, int(request.form.get("taille_pixel", 1))))
    except ValueError:
        return erreur("Paramètre invalide")
    methode = "net" if request.form.get("methode") == "net" else "lisse"
    colorier = request.form.get("colorier") == "1"

    img = core.redimensionner(img, taille_pixel, methode)
    matrice = core.image_vers_matrice(img)
    hauteur, largeur = matrice.shape

    grille = None
    if largeur * hauteur <= MAX_GRILLE_CASES:
        grille = png_base64(core.dessiner_grille(matrice, taille_case, colorier))

    return jsonify(
        largeur=largeur,
        hauteur=hauteur,
        csv=core.matrice_vers_csv(matrice),
        apercu=png_base64(core.matrice_vers_image(matrice)),
        png=grille,
        grille_max=MAX_GRILLE_CASES,
        comptage=core.compter_blocs(matrice),
    )


if __name__ == "__main__":
    app.run(debug=False)
