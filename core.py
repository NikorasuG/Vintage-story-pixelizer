"""Logique métier : image -> redimensionnement -> matrice de blocs (palette fixe) -> grille numérotée."""
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = 100_000_000   # protection contre les images démesurées
MAX_DIM = 480                         # plus grand côté maximum (en blocs) pour une taille de pixel de 1

# Palette fixe du jeu : l'indice dans la liste = numéro du bloc (0 à 79)
PALETTE_HEX = (
    "823e3b 844b3d 87593e 8a683f 8d7741 908741 888e41 768c41 668b40 568a40 "
    "48893f 3e8843 3e8a52 3e8a5f 3e8a6c 3f8978 408986 3f7983 3e6980 3c5a7d "
    "3a4b7b 383d78 403a78 4b3b79 573c7b 633d7c 703e7d 7a3e7a 7c3e6c 7d3e5f "
    "7e3d52 803d45 a3312f a94a33 ad6236 b27b3a b5943e b9ad41 abb640 93b43f "
    "7ab13d 66b03c 4aac39 3baa3f 3bab53 3cac67 3dae7b 3daf90 3db0a6 3899a6 "
    "347ea2 30649e 2d4b9a 293396 362c96 4b2e98 602f9b 77319d 8e329f 9f3399 "
    "9d3284 9c3270 973059 953044 030303 0e1010 1b1e1d 292d2b 393c39 484b47 "
    "585954 686761 78746e 86827c 928e88 9f9c97 aaa7a2 b6b3ae c2bfba cecac4"
).split()
assert len(PALETTE_HEX) == 80, "La palette doit contenir 80 couleurs"


def hex_vers_rgb(code):
    code = code.strip().lstrip("#")
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


PALETTE_RGB = [hex_vers_rgb(h) for h in PALETTE_HEX]
PALETTE_ARRAY = np.array(PALETTE_RGB, dtype=np.uint8)


# ---------- couleurs : recherche du bloc le plus proche (CIE Lab, vectorisé) ----------
_M_XYZ = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
_BLANC = np.array([0.95047, 1.0, 1.08883])


def _vers_lab(rgb):
    """rgb : tableau (n, 3) de 0 à 255 -> tableau (n, 3) en CIE Lab (plus proche de la perception que le RGB)."""
    c = np.asarray(rgb, dtype=np.float64) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = (lin @ _M_XYZ.T) / _BLANC
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


PALETTE_LAB = _vers_lab(PALETTE_ARRAY)


def _plus_proches(couleurs_rgb):
    """Numéro de bloc le plus proche pour chaque couleur d'un tableau (n, 3)."""
    lab = _vers_lab(couleurs_rgb)
    resultat = np.empty(len(lab), dtype=np.int16)
    for i in range(0, len(lab), 20000):                      # par paquets pour limiter la mémoire
        morceau = lab[i:i + 20000]
        distances = ((morceau[:, None, :] - PALETTE_LAB[None, :, :]) ** 2).sum(axis=2)
        resultat[i:i + 20000] = distances.argmin(axis=1)
    return resultat


# ---------- image ----------
def charger_image(flux):
    img = ImageOps.exif_transpose(Image.open(flux))   # respecte l'orientation des photos de téléphone
    return img.convert("RGBA")


def dimensions_cible(largeur, hauteur, taille_pixel=1, max_dim=MAX_DIM):
    """
    Le plus grand côté est ramené à max_dim (sans jamais agrandir), puis divisé par la taille d'un pixel.
    Ex : 2048 x 1024 -> 1024 x 512 (taille 1), 512 x 256 (taille 2), ...
    """
    echelle = min(1.0, max_dim / max(largeur, hauteur))
    return (max(1, round(largeur * echelle / taille_pixel)),
            max(1, round(hauteur * echelle / taille_pixel)))


def redimensionner(img, taille_pixel=1, methode="lisse"):
    """methode : 'lisse' (LANCZOS, pour les photos) ou 'net' (plus proche voisin, pour le pixel art)."""
    cible = dimensions_cible(img.width, img.height, taille_pixel)
    if cible == img.size:
        return img
    resample = Image.NEAREST if methode == "net" else Image.LANCZOS
    return img.resize(cible, resample)


def image_vers_matrice(img, valeur_transparent=-1):
    """Tableau numpy (hauteur, largeur) : numéro du bloc le plus proche pour chaque pixel."""
    arr = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    rgb = arr[..., :3].astype(np.uint32)
    packed = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
    uniques, inverse = np.unique(packed, return_inverse=True)   # chaque couleur n'est calculée qu'une fois
    couleurs = np.stack([(uniques >> 16) & 255, (uniques >> 8) & 255, uniques & 255], axis=1)
    matrice = _plus_proches(couleurs)[inverse.reshape(packed.shape)].astype(np.int16)
    matrice[arr[..., 3] < 128] = valeur_transparent
    return matrice


def matrice_vers_image(matrice):
    """Aperçu : l'image telle qu'elle sera avec les couleurs du jeu (transparent si -1)."""
    m = np.asarray(matrice)
    sortie = np.zeros(m.shape + (4,), dtype=np.uint8)
    masque = m >= 0
    sortie[masque, :3] = PALETTE_ARRAY[m[masque]]
    sortie[masque, 3] = 255
    return Image.fromarray(sortie, "RGBA")


def matrice_vers_csv(matrice):
    tampon = io.StringIO()
    np.savetxt(tampon, np.asarray(matrice), fmt="%d", delimiter=",")
    return tampon.getvalue()


def compter_blocs(matrice):
    m = np.asarray(matrice)
    compte = np.bincount(m[m >= 0].ravel(), minlength=80)
    return [[i, int(n)] for i, n in enumerate(compte) if n]


# ---------- grille numérotée ----------
def _police(taille):
    for nom in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def _texte_lisible(fond):
    lum = 0.299 * fond[0] + 0.587 * fond[1] + 0.114 * fond[2]
    return (0, 0, 0) if lum > 140 else (255, 255, 255)


def dessiner_grille(matrice, taille_case=28, colorier=True):
    """Retourne une Image PIL ; colorier=True remplit chaque case avec la couleur du bloc."""
    matrice = np.asarray(matrice).tolist()
    matrice = np.asarray(matrice).tolist()
    hauteur, largeur = len(matrice), len(matrice[0])
    marge_g, marge_h = int(taille_case * 1.6), taille_case
    img = Image.new("RGB", (marge_g + largeur * taille_case + 2, marge_h + hauteur * taille_case + 2), "white")
    d = ImageDraw.Draw(img)
    police = _police(max(8, int(taille_case * 0.45)))
    police_repere = _police(max(8, int(taille_case * 0.38)))

    for y, ligne in enumerate(matrice):
        for x, num in enumerate(ligne):
            px, py = marge_g + x * taille_case, marge_h + y * taille_case
            if num < 0:
                fond, texte = (225, 225, 225), None
            else:
                fond = PALETTE_RGB[num] if colorier else (255, 255, 255)
                texte = str(num)
            d.rectangle([px, py, px + taille_case, py + taille_case], fill=fond, outline=(170, 170, 170))
            if texte:
                d.text((px + taille_case / 2, py + taille_case / 2), texte,
                       fill=_texte_lisible(fond), font=police, anchor="mm")

    for x in range(largeur):
        if (x + 1) % 5 == 0 or x == 0:
            d.text((marge_g + x * taille_case + taille_case / 2, marge_h / 2), str(x + 1),
                   fill=(80, 80, 80), font=police_repere, anchor="mm")
    for y in range(hauteur):
        if (y + 1) % 5 == 0 or y == 0:
            d.text((marge_g / 2, marge_h + y * taille_case + taille_case / 2), str(y + 1),
                   fill=(80, 80, 80), font=police_repere, anchor="mm")

    for x in range(0, largeur + 1, 10):
        px = marge_g + x * taille_case
        d.line([px, marge_h, px, marge_h + hauteur * taille_case], fill=(0, 0, 0), width=2)
    for y in range(0, hauteur + 1, 10):
        py = marge_h + y * taille_case
        d.line([marge_g, py, marge_g + largeur * taille_case, py], fill=(0, 0, 0), width=2)
    return img
