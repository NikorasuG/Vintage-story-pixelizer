"""Voxelisation d'un maillage STL (plein) par lancer de rayons le long de l'axe vertical."""
import re
import struct

import numpy as np

HAUTEUR_MAX = 256          # nombre maximum de voxels en hauteur
MAX_CELLES = 8_000_000     # taille maximale de la grille (nx * ny * nz)
_EPS_X, _EPS_Y = 1.3e-3, 7.1e-4   # décalage des rayons : évite de tomber pile sur une arête
_LOT = 2_000_000           # nombre max de couples (triangle, colonne) traités à la fois


# ---------- lecture STL ----------
def lire_stl(octets):
    """STL binaire ou ASCII -> tableau (n, 3, 3) de sommets (float64)."""
    if len(octets) >= 84:
        n = struct.unpack("<I", octets[80:84])[0]
        if n > 0 and 84 + 50 * n == len(octets):
            dt = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
            return np.frombuffer(octets, dtype=dt, count=n, offset=84)["v"].astype(np.float64)

    texte = octets.decode("utf-8", errors="ignore")
    sommets = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", texte)
    if not sommets or len(sommets) % 3:
        raise ValueError("Fichier STL invalide ou vide")
    try:
        return np.array(sommets, dtype=np.float64).reshape(-1, 3, 3)
    except ValueError:
        raise ValueError("Fichier STL invalide (coordonnées illisibles)")


def orienter(tri, axe_vertical):
    """Permutation circulaire des axes (conserve la chiralité) pour que l'axe choisi devienne Z."""
    ordre = {"z": (0, 1, 2), "x": (1, 2, 0), "y": (2, 0, 1)}[axe_vertical]
    return tri[:, :, ordre]


# ---------- voxelisation ----------
def _intersections(tri, nx, ny):
    """Pour chaque colonne (i, j), altitudes où le rayon vertical traverse la surface."""
    x, y, z = tri[..., 0], tri[..., 1], tri[..., 2]
    i0 = np.maximum(np.ceil(x.min(1) - 0.5 - _EPS_X), 0).astype(np.int64)
    i1 = np.minimum(np.floor(x.max(1) - 0.5 - _EPS_X), nx - 1).astype(np.int64)
    j0 = np.maximum(np.ceil(y.min(1) - 0.5 - _EPS_Y), 0).astype(np.int64)
    j1 = np.minimum(np.floor(y.max(1) - 0.5 - _EPS_Y), ny - 1).astype(np.int64)
    w, h = i1 - i0 + 1, j1 - j0 + 1
    utiles = np.nonzero((w > 0) & (h > 0))[0]
    nb = (w * h)[utiles]
    cumul = np.cumsum(nb)

    cols, zs = [], []
    debut = 0
    while debut < len(utiles):
        base = cumul[debut - 1] if debut else 0
        fin = max(int(np.searchsorted(cumul, base + _LOT, side="right")), debut + 1)
        sel, c = utiles[debut:fin], nb[debut:fin]
        debut = fin

        t = np.repeat(sel, c)
        local = np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)
        i = i0[t] + local % w[t]
        j = j0[t] + local // w[t]
        px, py = i + 0.5 + _EPS_X, j + 0.5 + _EPS_Y

        x0, x1, x2 = x[t, 0], x[t, 1], x[t, 2]
        y0, y1, y2 = y[t, 0], y[t, 1], y[t, 2]
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        ok = np.abs(d) > 1e-12                       # triangles verticaux : ignorés
        d = np.where(ok, d, 1.0)
        l0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / d
        l1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / d
        l2 = 1 - l0 - l1
        dedans = ok & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)

        cols.append((j * nx + i)[dedans])
        zs.append((l0 * z[t, 0] + l1 * z[t, 1] + l2 * z[t, 2])[dedans])

    if not cols:
        return np.empty(0, np.int64), np.empty(0)
    return np.concatenate(cols), np.concatenate(zs)


def voxeliser(tri, n_hauteur, axe_vertical="z"):
    """
    tri : (n, 3, 3) sommets du maillage. n_hauteur : nombre de voxels (couches) en hauteur.
    Retourne (grille bool (nz, ny, nx), infos dict, avertissement ou None).
    """
    if not 1 <= n_hauteur <= HAUTEUR_MAX:
        raise ValueError(f"La hauteur doit être comprise entre 1 et {HAUTEUR_MAX} voxels")
    tri = orienter(tri, axe_vertical)
    if not np.isfinite(tri).all():
        raise ValueError("Le maillage contient des coordonnées invalides")

    mini, maxi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    etendue = maxi - mini
    if etendue[2] <= 0:
        raise ValueError("Le modèle n'a aucune hauteur selon l'axe vertical choisi")

    pas = etendue[2] / n_hauteur                        # taille d'un voxel (cubique)
    nz = n_hauteur
    nx = max(1, int(np.ceil(etendue[0] / pas - 1e-9)))
    ny = max(1, int(np.ceil(etendue[1] / pas - 1e-9)))
    if nx * ny * nz > MAX_CELLES:
        h_max = max(1, int(n_hauteur * (MAX_CELLES / (nx * ny * nz)) ** (1 / 3)))
        def esp(v):
            return f"{v:_}".replace("_", " ")
        raise ValueError(f"Grille trop grande ({nx}×{ny}×{nz} = {esp(nx * ny * nz)} cases, maximum {esp(MAX_CELLES)}). "
                         f"Essaie une hauteur d'environ {h_max} voxels ou moins.")

    g = (tri - mini) / pas                              # coordonnées en unités de voxel
    colonnes, z = _intersections(g, nx, ny)
    ncols = nx * ny

    avert = None
    if len(colonnes) == 0:
        raise ValueError("Aucune surface trouvée : le maillage est vide ou dégénéré")

    ordre = np.lexsort((z, colonnes))
    c, z = colonnes[ordre], z[ordre]
    total = np.bincount(c, minlength=ncols)
    impaires = int((total % 2 == 1).sum())
    if impaires > 0.01 * max(1, int((total > 0).sum())):
        avert = ("Le maillage ne semble pas fermé (étanche) : le remplissage peut être incomplet. "
                 "Répare le modèle (par ex. dans Blender ou MeshLab) si le résultat est faux.")

    n = len(c)
    debut_groupe = np.maximum.accumulate(np.where(np.r_[True, c[1:] != c[:-1]], np.arange(n), 0))
    rang = np.arange(n) - debut_groupe
    sorties = np.nonzero(rang % 2 == 1)[0]              # chaque sortie est appariée à l'entrée qui la précède
    z_in, z_out, col = z[sorties - 1], z[sorties], c[sorties]

    k0 = np.maximum(np.ceil(z_in - 0.5), 0).astype(np.int64)
    k1 = np.minimum(np.floor(z_out - 0.5), nz - 1).astype(np.int64)
    v = k1 >= k0
    taille = (nz + 1) * ncols
    diff = (np.bincount(k0[v] * ncols + col[v], minlength=taille)
            - np.bincount((k1[v] + 1) * ncols + col[v], minlength=taille)).astype(np.int32)
    grille = (np.cumsum(diff.reshape(nz + 1, ncols), axis=0)[:nz] > 0).reshape(nz, ny, nx)

    infos = {"nx": nx, "ny": ny, "nz": nz, "pas": float(pas),
             "dimensions": [float(e) for e in etendue], "triangles": int(len(tri)),
             "remplis": int(grille.sum())}
    return grille, infos, avert
