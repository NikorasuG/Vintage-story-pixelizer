// ======================= logique pure (testable sous Node) =======================
// La grille est un Uint8Array indexé par x + nx * (y + ny * z), z = numéro de couche (0 = bas).

function depaqueter(b64, total) {
  const bin = atob(b64);
  const oct = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) oct[i] = bin.charCodeAt(i);
  const out = new Uint8Array(total);
  for (let i = 0; i < total; i++) out[i] = (oct[i >> 3] >> (7 - (i & 7))) & 1;
  return out;
}

function compterParCouche(grille, nx, ny, nz) {
  const n = nx * ny, cnt = new Int32Array(nz);
  for (let z = 0; z < nz; z++) {
    let c = 0;
    for (let i = z * n, f = i + n; i < f; i++) c += grille[i];
    cnt[z] = c;
  }
  return cnt;
}

// Voxels à dessiner pour les couches lo..hi : ceux qui ont au moins une face exposée
// (les voisins hors de la plage lo..hi comptent comme vides, donc la coupe est bien "pleine").
function voxelsVisibles(grille, nx, ny, nz, lo, hi, cnt) {
  let borne = 0;
  for (let z = lo; z <= hi; z++) borne += cnt[z];
  const sortie = new Int32Array(borne);
  const plein = (x, y, z) =>
    x >= 0 && x < nx && y >= 0 && y < ny && z >= lo && z <= hi && grille[x + nx * (y + ny * z)] === 1;
  let n = 0;
  for (let z = lo; z <= hi; z++) {
    for (let y = 0; y < ny; y++) {
      for (let x = 0; x < nx; x++) {
        const idx = x + nx * (y + ny * z);
        if (grille[idx] !== 1) continue;
        if (!(plein(x - 1, y, z) && plein(x + 1, y, z) && plein(x, y - 1, z) &&
              plein(x, y + 1, z) && plein(x, y, z - 1) && plein(x, y, z + 1))) sortie[n++] = idx;
      }
    }
  }
  return sortie.subarray(0, n);
}

function csvCouches(grille, nx, ny, nz) {
  const lignes = [];
  for (let z = 0; z < nz; z++) {
    lignes.push(`# couche ${z + 1}`);
    for (let y = ny - 1; y >= 0; y--) {          // première ligne = côté "nord" (y max)
      const ligne = new Array(nx);
      for (let x = 0; x < nx; x++) ligne[x] = grille[x + nx * (y + ny * z)];
      lignes.push(ligne.join(","));
    }
    lignes.push("");
  }
  return lignes.join("\n");
}

// ======================= interface =======================
if (typeof document === "undefined") {
  module.exports = { depaqueter, compterParCouche, voxelsVisibles, csvCouches };
} else {
  (() => {
    const $ = (s) => document.querySelector(s);
    const ACCENT = [0.91, 0.52, 0.24];
    let fichier = null;
    let modele = null;       // {grille, nx, ny, nz, cnt, infos}
    let vue = null;          // {renderer, scene, camera, controls, mesh, grid}
    let planifie = false;

    // ---------- envoi du fichier ----------
    function choisirFichier(f) {
      fichier = f;
      $("#nom-fichier").textContent = f.name;
      $("#btn-voxeliser").disabled = false;
      $("#erreur").textContent = "";
    }

    async function voxeliser() {
      if (!fichier) return;
      $("#erreur").textContent = "";
      $("#avertissement").hidden = true;
      $("#info").textContent = "Voxelisation en cours…";
      $("#btn-voxeliser").disabled = true;
      const fd = new FormData();
      fd.append("stl", fichier);
      fd.append("hauteur", $("#hauteur").value);
      fd.append("axe", $("#axe").value);
      try {
        const r = await fetch("/api/voxelize", { method: "POST", body: fd });
        const d = await r.json();
        if (!r.ok) { $("#info").textContent = ""; $("#erreur").textContent = d.error; return; }
        chargerModele(d);
      } catch {
        $("#info").textContent = "";
        $("#erreur").textContent = "Erreur de communication avec le serveur.";
      } finally {
        $("#btn-voxeliser").disabled = false;
      }
    }

    function chargerModele(d) {
      const { nx, ny, nz } = d;
      const grille = depaqueter(d.bits, nx * ny * nz);
      modele = { grille, nx, ny, nz, cnt: compterParCouche(grille, nx, ny, nz), infos: d };

      const dim = d.dimensions.map((v) => +v.toPrecision(4)).join(" × ");
      $("#info").textContent =
        `Modèle ${dim} (unités du fichier) · voxel ${d.pas.toPrecision(3)} · grille ${nx} × ${ny} × ${nz} · ` +
        `${d.remplis.toLocaleString("fr-FR")} voxels · ${d.triangles.toLocaleString("fr-FR")} triangles`;
      if (d.avertissement) { $("#avertissement").textContent = d.avertissement; $("#avertissement").hidden = false; }

      $("#resultat").hidden = false;
      const c = $("#couche");
      c.max = nz; c.value = nz;
      $("#couche-max").textContent = nz;
      initialiserVue();
      construireGrille();
      cadrer();
      rafraichir();
    }

    // ---------- vue 3D ----------
    function initialiserVue() {
      if (vue) return;
      const conteneur = $("#vue");
      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      conteneur.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x15171c);
      const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
      scene.add(camera);
      camera.add(new THREE.AmbientLight(0xffffff, 0.6));
      const lumiere = new THREE.DirectionalLight(0xffffff, 0.85);   // attachée à la caméra : toujours bien éclairé
      lumiere.position.set(0.6, 1, 0.8);
      camera.add(lumiere);

      const controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      vue = { renderer, scene, camera, controls, mesh: null, grid: null,
              geo: new THREE.BoxGeometry(1, 1, 1), mat: new THREE.MeshLambertMaterial() };

      const ajuster = () => {
        const w = conteneur.clientWidth, h = conteneur.clientHeight;
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      };
      new ResizeObserver(ajuster).observe(conteneur);
      ajuster();
      (function boucle() { requestAnimationFrame(boucle); controls.update(); renderer.render(scene, camera); })();
    }

    function construireGrille() {
      const { nx, ny } = modele;
      if (vue.grid) { vue.scene.remove(vue.grid); vue.grid.geometry.dispose(); }
      const t = Math.max(nx, ny) + 4;
      vue.grid = new THREE.GridHelper(t, t, 0x3a404c, 0x262a33);
      vue.grid.position.y = -0.02;
      vue.scene.add(vue.grid);
    }

    function cadrer() {
      const { nx, ny, nz } = modele;
      const d = Math.max(nx, ny, nz) * 1.9;
      vue.camera.position.set(d * 0.75, nz / 2 + d * 0.55, d * 0.9);
      vue.controls.target.set(0, nz / 2, 0);
      vue.controls.update();
    }

    function couleurCouche(z, nz) {
      const t = nz > 1 ? z / (nz - 1) : 1;
      return [0.30 + 0.25 * t, 0.37 + 0.30 * t, 0.50 + 0.30 * t];   // bleu-gris, plus clair vers le haut
    }

    function mettreAJourVue(lo, hi) {
      const { grille, nx, ny, nz, cnt } = modele;
      const idx = voxelsVisibles(grille, nx, ny, nz, lo, hi, cnt);
      if (vue.mesh) { vue.scene.remove(vue.mesh); vue.mesh.dispose(); vue.mesh = null; }
      if (!idx.length) return;

      const mesh = new THREE.InstancedMesh(vue.geo, vue.mat, idx.length);
      const m = mesh.instanceMatrix.array;
      const col = new Float32Array(idx.length * 3);
      const seule = lo === hi;
      const S = 0.97;   // léger espace entre voxels pour mieux les distinguer
      for (let i = 0; i < idx.length; i++) {
        const v = idx[i], x = v % nx, y = ((v / nx) | 0) % ny, z = (v / (nx * ny)) | 0;
        const o = i * 16;
        m[o] = S; m[o + 5] = S; m[o + 10] = S; m[o + 15] = 1;
        m[o + 12] = x + 0.5 - nx / 2;
        m[o + 13] = z + 0.5;
        m[o + 14] = -(y + 0.5) + ny / 2;
        const c = (z === hi || seule) ? ACCENT : couleurCouche(z, nz);   // la couche choisie ressort en orange
        col[i * 3] = c[0]; col[i * 3 + 1] = c[1]; col[i * 3 + 2] = c[2];
      }
      mesh.instanceColor = new THREE.InstancedBufferAttribute(col, 3);
      mesh.instanceMatrix.needsUpdate = true;
      vue.scene.add(mesh);
      vue.mesh = mesh;
    }

    // ---------- vue 2D de la couche ----------
    function dessiner2D(k, seule) {
      const { grille, nx, ny } = modele;
      const cv = $("#vue2d");
      const cell = Math.max(1, Math.floor(420 / Math.max(nx, ny)));
      cv.width = nx * cell; cv.height = ny * cell;
      const ctx = cv.getContext("2d");
      ctx.fillStyle = "#0f1115";
      ctx.fillRect(0, 0, cv.width, cv.height);
      const couche = (z, couleur) => {
        ctx.fillStyle = couleur;
        for (let y = 0; y < ny; y++)
          for (let x = 0; x < nx; x++)
            if (grille[x + nx * (y + ny * z)]) ctx.fillRect(x * cell, (ny - 1 - y) * cell, cell, cell);
      };
      if (k > 0 && !seule) couche(k - 1, "#3a404c");
      couche(k, "#e8843c");
      if (cell >= 6) {
        ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 1;
        for (let x = 0; x <= nx; x++) { ctx.beginPath(); ctx.moveTo(x * cell + 0.5, 0); ctx.lineTo(x * cell + 0.5, cv.height); ctx.stroke(); }
        for (let y = 0; y <= ny; y++) { ctx.beginPath(); ctx.moveTo(0, y * cell + 0.5); ctx.lineTo(cv.width, y * cell + 0.5); ctx.stroke(); }
      }
    }

    // ---------- rafraîchissement ----------
    function rafraichir() {
      if (!modele || planifie) return;
      planifie = true;
      requestAnimationFrame(() => {
        planifie = false;
        const k = parseInt($("#couche").value, 10) - 1;
        const seule = document.querySelector('input[name="mode"]:checked').value === "seule";
        $("#couche-val").textContent = k + 1;
        mettreAJourVue(seule ? k : 0, k);
        dessiner2D(k, seule);
        let affiches = 0;
        for (let z = seule ? k : 0; z <= k; z++) affiches += modele.cnt[z];
        $("#stats").textContent =
          `${modele.cnt[k].toLocaleString("fr-FR")} voxels dans cette couche · ` +
          `${affiches.toLocaleString("fr-FR")} affichés sur ${modele.infos.remplis.toLocaleString("fr-FR")}`;
      });
    }

    function deplacerCouche(delta) {
      const c = $("#couche");
      c.value = Math.min(parseInt(c.max, 10), Math.max(1, parseInt(c.value, 10) + delta));
      rafraichir();
    }

    function exporter() {
      const { grille, nx, ny, nz } = modele;
      const lien = document.createElement("a");
      lien.href = URL.createObjectURL(new Blob([csvCouches(grille, nx, ny, nz)], { type: "text/csv" }));
      lien.download = "couches_voxels.csv";
      lien.click();
      URL.revokeObjectURL(lien.href);
    }

    // ---------- évènements ----------
    $("#fichier").addEventListener("change", (e) => e.target.files[0] && choisirFichier(e.target.files[0]));
    const zone = $("#zone-depot");
    ["dragover", "dragenter"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("survol"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, () => zone.classList.remove("survol")));
    zone.addEventListener("drop", (e) => { e.preventDefault(); e.dataTransfer.files[0] && choisirFichier(e.dataTransfer.files[0]); });

    // hauteur : curseur et champ numérique synchronisés
    const borner = (v) => Math.min(parseInt($("#hauteur").max, 10), Math.max(1, v || 1));
    $("#hauteur-range").addEventListener("input", (e) => { $("#hauteur").value = e.target.value; });
    $("#hauteur").addEventListener("input", (e) => { $("#hauteur-range").value = borner(parseInt(e.target.value, 10)); });
    $("#hauteur").addEventListener("change", (e) => { e.target.value = borner(parseInt(e.target.value, 10)); $("#hauteur-range").value = e.target.value; });

    $("#btn-voxeliser").addEventListener("click", voxeliser);
    $("#couche").addEventListener("input", rafraichir);
    $("#couche-moins").addEventListener("click", () => deplacerCouche(-1));
    $("#couche-plus").addEventListener("click", () => deplacerCouche(1));
    document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", rafraichir));
    $("#btn-recentrer").addEventListener("click", () => modele && cadrer());
    $("#btn-export").addEventListener("click", () => modele && exporter());
    window.addEventListener("keydown", (e) => {
      if (!modele || /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName) && document.activeElement.type !== "range") return;
      if (e.key === "ArrowUp" || e.key === "PageUp") { e.preventDefault(); deplacerCouche(e.key === "PageUp" ? 5 : 1); }
      if (e.key === "ArrowDown" || e.key === "PageDown") { e.preventDefault(); deplacerCouche(e.key === "PageDown" ? -5 : -1); }
    });
  })();
}
