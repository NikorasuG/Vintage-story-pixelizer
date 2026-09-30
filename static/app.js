const $ = (s) => document.querySelector(s);
let fichier = null;
let tailleOrigine = null;   // {l, h} de l'image chargée
let minuterie = null;

const montrerErreur = (msg) => { $("#erreur").textContent = msg || ""; };

// Même règle que le serveur (core.dimensions_cible)
function dimensionsCible(l, h, taillePixel) {
  const echelle = Math.min(1, window.MAX_DIM / Math.max(l, h));
  return [Math.max(1, Math.round(l * echelle / taillePixel)), Math.max(1, Math.round(h * echelle / taillePixel))];
}

function majDimensions() {
  const t = parseInt($("#taille-pixel").value, 10);
  $("#pixel-val").textContent = t;
  if (!tailleOrigine) return;
  const [l, h] = dimensionsCible(tailleOrigine.l, tailleOrigine.h, t);
  $("#dims").textContent = `Image d'origine ${tailleOrigine.l} × ${tailleOrigine.h} px → ${l} × ${h} blocs (${l * h} au total)`;
}

async function generer() {
  if (!fichier) return;
  montrerErreur("");
  const fd = new FormData();
  fd.append("image", fichier);
  fd.append("taille_pixel", $("#taille-pixel").value);
  fd.append("methode", $("#methode").value);
  fd.append("taille_case", $("#taille-case").value);
  fd.append("colorier", $("#colorier").checked ? "1" : "0");

  $("#btn-generer").disabled = true;
  $("#info").textContent = "Génération en cours…";
  try {
    const r = await fetch("/api/generate", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) { $("#info").textContent = ""; return montrerErreur(data.error); }
    afficherResultat(data);
  } catch {
    $("#info").textContent = "";
    montrerErreur("Erreur de communication avec le serveur.");
  } finally {
    $("#btn-generer").disabled = false;
  }
}

function afficherResultat(data) {
  $("#info").textContent = `${data.largeur} × ${data.hauteur} blocs (${data.largeur * data.hauteur} au total)`;
  $("#apercu").src = "data:image/png;base64," + data.apercu;
  $("#dl-csv").href = URL.createObjectURL(new Blob([data.csv], { type: "text/csv" }));

  if (data.png) {
    $("#grille").src = "data:image/png;base64," + data.png;
    $("#dl-png").href = "data:image/png;base64," + data.png;
    $("#bloc-grille").hidden = false;
    $("#note-grille").hidden = true;
    appliquerZoom();
  } else {
    $("#bloc-grille").hidden = true;
    $("#note-grille").hidden = false;
    $("#note-grille").textContent =
      `Grille numérotée non générée : ${data.largeur * data.hauteur} cases (maximum ${data.grille_max}). ` +
      `Augmente la taille d'un pixel pour réduire le nombre de blocs, ou utilise la matrice CSV.`;
  }

  const corps = $("#table-comptage tbody");
  corps.replaceChildren();
  for (const [num, qte] of data.comptage) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><span class="pastille" style="background:#${window.PALETTE[num]}"></span></td><td>${num}</td><td>${qte}</td>`;
    corps.appendChild(tr);
  }
  $("#resultat").hidden = false;
}

function appliquerZoom() {
  const z = $("#zoom").value;
  $("#zoom-val").textContent = z + "%";
  $("#grille").style.width = z + "%";
}

function choisirFichier(f) {
  fichier = f;
  const url = URL.createObjectURL(f);
  $("#original").src = url;
  const sonde = new Image();
  sonde.onload = () => {
    tailleOrigine = { l: sonde.naturalWidth, h: sonde.naturalHeight };
    // la taille de pixel maximale dépend de la taille de l'image (au moins 2 blocs restent)
    const plusGrand = Math.max(sonde.naturalWidth, sonde.naturalHeight);
    const cote = Math.min(plusGrand, window.MAX_DIM);
    const max = Math.max(2, Math.min(64, Math.floor(cote / 4)));
    $("#taille-pixel").max = max;
    if (parseInt($("#taille-pixel").value, 10) > max) $("#taille-pixel").value = max;
    majDimensions();
  };
  sonde.src = url;
  $("#btn-generer").disabled = false;
  generer();
}

// ---------- évènements ----------
$("#fichier").addEventListener("change", (e) => e.target.files[0] && choisirFichier(e.target.files[0]));
const zone = $("#zone-depot");
["dragover", "dragenter"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("survol"); }));
["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, () => zone.classList.remove("survol")));
zone.addEventListener("drop", (e) => { e.preventDefault(); e.dataTransfer.files[0] && choisirFichier(e.dataTransfer.files[0]); });

$("#taille-pixel").addEventListener("input", () => {
  majDimensions();
  clearTimeout(minuterie);
  minuterie = setTimeout(generer, 400);   // on attend que le curseur se stabilise
});
$("#methode").addEventListener("change", generer);
$("#btn-generer").addEventListener("click", generer);
$("#zoom").addEventListener("input", appliquerZoom);
majDimensions();
