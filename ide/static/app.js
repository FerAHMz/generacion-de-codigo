/* Compiscript IDE — lógica del cliente */
(function () {
  const DEFAULT_SOURCE = `// Escribe tu programa Compiscript aquí y presiona Compilar.
const PI: integer = 314;
let saludo: string = "Hola, Compiscript!";

function factorial(n: integer): integer {
  if (n <= 1) { return 1; }
  return n * factorial(n - 1);
}

class Animal {
  let nombre: string;
  function constructor(nombre: string) { this.nombre = nombre; }
  function hablar(): string { return this.nombre + " hace ruido."; }
}

let a: Animal = new Animal("Toby");
print(a.hablar());
print(factorial(5));
`;

  const editor = CodeMirror.fromTextArea(document.getElementById("code"), {
    mode: "javascript", theme: "material-darker", lineNumbers: true, matchBrackets: true,
    autoCloseBrackets: true, indentUnit: 2, tabSize: 2, gutters: ["error-gutter", "CodeMirror-linenumbers"],
    extraKeys: { "Ctrl-Enter": run, "Cmd-Enter": run },
  });
  editor.setValue(localStorage.getItem("cps.source") || DEFAULT_SOURCE);

  const $ = (id) => document.getElementById(id);
  const status = $("status"), errList = $("errors"), errCount = $("err-count");
  const symBody = document.querySelector("#symbols tbody"), treeBox = $("tree");
  const tacBox = $("tac"), runtimeBox = $("runtime"), outputBox = $("output");
  const mipsBox = $("mips"), mipsInfo = $("mips-info"), downloadBtn = $("download"), regallocSel = $("regalloc");
  let markers = [], timer = null, asmText = "";
  try { regallocSel.value = localStorage.getItem("cps.regalloc") || "linear"; } catch (e) { /* sin storage */ }

  // --- pestañas -------------------------------------------------------------
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button, .tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); $("tab-" + b.dataset.tab).classList.add("active");
  }));

  // --- ejemplos -------------------------------------------------------------
  fetch("/api/examples").then((r) => r.json()).then((names) => {
    names.forEach((n) => { const o = document.createElement("option"); o.value = n; o.textContent = n; $("examples").appendChild(o); });
  });
  $("examples").addEventListener("change", (e) => {
    if (!e.target.value) return;
    fetch("/api/examples/" + encodeURIComponent(e.target.value)).then((r) => r.text()).then((src) => { editor.setValue(src); run(); });
  });

  // --- análisis -------------------------------------------------------------
  function clearMarks() {
    markers.forEach((m) => m.clear && m.clear());
    markers = [];
    editor.eachLine((l) => { editor.removeLineClass(l, "background", "error-line"); });
    editor.clearGutter("error-gutter");
  }

  function run() {
    const source = editor.getValue();
    localStorage.setItem("cps.source", source);
    status.textContent = "analizando…"; status.className = "status";
    fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }) })
      .then((r) => r.json()).then(render).catch((err) => { status.textContent = "error de conexión"; status.className = "status bad"; console.error(err); });
    compile(source);
  }

  function clearOutput() {
    outputBox.innerHTML = '<span class="muted">Presiona «Ejecutar TAC» para correr el código intermedio con el intérprete.</span>';
  }

  function compile(source) {
    const regalloc = regallocSel.value;
    fetch("/api/compile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source, regalloc }) })
      .then((r) => r.json()).then(renderCompile).catch((err) => console.error(err));
  }

  // --- código intermedio y registros de activación ----------------------------
  function renderCompile(data) {
    tacBox.innerHTML = "";
    if (!data.tac.length) {
      tacBox.innerHTML = `<span class="muted">${data.errors.length ? "Hay errores: no se generó código intermedio." : "(sin instrucciones)"}</span>`;
    } else {
      const width = String(data.tac.length).length;
      tacBox.innerHTML = data.tac.map((ln, i) => {
        const num = `<span class="ln">${String(i + 1).padStart(width)}</span>  `;
        const [code, ...comment] = ln.split("    # ");
        const body = /^\S/.test(code) ? `<span class="${code.startsWith("func_") ? "fn" : "lbl"}">${escapeHtml(code)}</span>` : escapeHtml(code);
        return num + body + (comment.length ? `<span class="muted">    # ${escapeHtml(comment.join("    # "))}</span>` : "");
      }).join("\n");
    }
    renderRuntime(data.symbols);
    renderMips(data);
  }

  // --- MIPS ------------------------------------------------------------------
  const MIPS_DIRECTIVE = /^\s*\.(data|text|globl|word|asciiz|space|float|align|byte)\b/;
  function highlightMips(line) {
    const hash = line.indexOf("#");
    const code = hash >= 0 ? line.slice(0, hash) : line;
    const comment = hash >= 0 ? `<span class="muted">${escapeHtml(line.slice(hash))}</span>` : "";
    let html;
    const label = code.match(/^([A-Za-z_][\w.]*:)(.*)$/);
    if (label) {
      html = `<span class="${label[1].startsWith("__") ? "lbl" : "fn"}">${escapeHtml(label[1])}</span>` + highlightOperands(label[2]);
    } else if (MIPS_DIRECTIVE.test(code)) {
      html = `<span class="dir">${escapeHtml(code)}</span>`;
    } else {
      const m = code.match(/^(\s*)(\S+)(.*)$/);
      html = m ? escapeHtml(m[1]) + `<span class="op">${escapeHtml(m[2])}</span>` + highlightOperands(m[3]) : escapeHtml(code);
    }
    return html + comment;
  }
  function highlightOperands(text) {
    return escapeHtml(text).replace(/(\$[a-z0-9]+)/g, '<span class="reg">$1</span>');
  }

  function renderMips(data) {
    asmText = data.mips && data.mips.length ? data.mips.join("\n") + "\n" : "";
    downloadBtn.disabled = !asmText;
    if (!asmText) {
      const why = data.errors.length ? "Hay errores: no se generó MIPS."
        : data.mips_error ? "Todavía sin traducción a MIPS: " + data.mips_error : "(sin código)";
      mipsBox.innerHTML = `<span class="muted">${escapeHtml(why)}</span>`;
      mipsInfo.textContent = "";
      return;
    }
    mipsBox.innerHTML = data.mips.map(highlightMips).join("\n");
    const n = data.mips.filter((l) => /^\s+[a-z]/.test(l.split("#")[0]) && !MIPS_DIRECTIVE.test(l)).length;
    mipsInfo.textContent = `${n} instrucciones · modo ${data.regalloc}`;
  }

  downloadBtn.addEventListener("click", () => {
    if (!asmText) return;
    const url = URL.createObjectURL(new Blob([asmText], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url; a.download = "programa.asm";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });

  regallocSel.addEventListener("change", () => {
    try { localStorage.setItem("cps.regalloc", regallocSel.value); } catch (e) { /* sin storage */ }
    compile(editor.getValue());
  });

  function executeMars() {
    outputBox.innerHTML = '<span class="muted">ejecutando en MARS…</span>';
    document.querySelector('.tabs button[data-tab="output"]').click();
    const body = JSON.stringify({ source: editor.getValue(), engine: "mars", regalloc: regallocSel.value });
    fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body })
      .then((r) => r.json()).then((data) => {
        if (!data.ok) { outputBox.innerHTML = '<span class="err">El programa tiene errores: no se genera MIPS.</span>'; return; }
        if (data.exit_code === null) { outputBox.innerHTML = `<span class="err">${escapeHtml(data.error || "no se pudo ejecutar MARS")}</span>`; return; }
        const lines = data.output.map(escapeHtml);
        if (data.runtime_error) lines.push(`<span class="err">${escapeHtml(data.runtime_error)}</span>`);
        if (data.error) lines.push(`<span class="err">${escapeHtml(data.error)}</span>`);
        if (!lines.length) lines.push('<span class="muted">(sin salida)</span>');
        lines.push(`<span class="muted">— MARS (${escapeHtml(data.regalloc)}) terminó con código ${data.exit_code}</span>`);
        outputBox.innerHTML = lines.join("\n");
      }).catch((err) => { outputBox.innerHTML = '<span class="err">error de conexión</span>'; console.error(err); });
  }

  function renderRuntime(symbols) {
    runtimeBox.innerHTML = "";
    const add = (html) => runtimeBox.insertAdjacentHTML("beforeend", html);
    add(`<h3>Área global <span class="muted">${symbols.globals_size} bytes</span></h3>`);
    symbols.activation_records.forEach((ar) => {
      const link = ar.static_link ? `, static link → ${escapeHtml(ar.static_link)}` : "";
      const header = ar.header.length
        ? ar.header.map((h) => `<li><code>fp[+${h.offset}]</code> ${h.field.replace("_", " ")} — <span class="muted">${escapeHtml(h.use)}</span></li>`).join("")
        : `<li class="muted">sin encabezado (nadie la llama)</li>`;
      const rows = ar.slots.map((s) => `<tr><td>${escapeHtml(s.address)}</td><td>${escapeHtml(s.content)}</td><td>${s.size}</td><td class="muted">${escapeHtml(s.use)}</td></tr>`).join("");
      add(`<div class="card"><h3>${escapeHtml(ar.label)} <span class="muted">nivel ${ar.level}${link} · frame_size = ${ar.frame_size} · temporales = ${ar.temps}</span></h3>` +
        `<ul class="header">${header}</ul>` +
        (rows ? `<table><thead><tr><th>Dirección</th><th>Contenido</th><th>Bytes</th><th>Uso</th></tr></thead><tbody>${rows}</tbody></table>` : "") + `</div>`);
    });
    symbols.classes.forEach((c) => {
      const fields = c.fields.map((f) => `<tr><td>[obj + ${f.offset}]</td><td>${escapeHtml(f.name)}</td><td>${f.size}</td><td class="muted">${escapeHtml(f.declared_in)}</td></tr>`).join("");
      const vtable = c.vtable.map((m) => `<li>vtable[${m.slot}] ${escapeHtml(m.method)} → <code>${escapeHtml(m.label)}</code></li>`).join("");
      add(`<div class="card"><h3>Clase ${escapeHtml(c.name)}${c.parent ? " : " + escapeHtml(c.parent) : ""} <span class="muted">object_size = ${c.object_size}</span></h3>` +
        `<table><thead><tr><th>Offset</th><th>Atributo</th><th>Bytes</th><th>Declarado en</th></tr></thead><tbody><tr><td>[obj + 0]</td><td>vtable</td><td>4</td><td></td></tr>${fields}</tbody></table>` +
        `<ul class="header">${vtable}${c.constructor ? `<li>constructor → <code>${escapeHtml(c.constructor)}</code></li>` : ""}</ul></div>`);
    });
  }

  // --- ejecución con el intérprete ---------------------------------------------
  function execute() {
    outputBox.innerHTML = '<span class="muted">ejecutando…</span>';
    document.querySelector('.tabs button[data-tab="output"]').click();
    fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source: editor.getValue() }) })
      .then((r) => r.json()).then((data) => {
        if (!data.ok) { outputBox.innerHTML = '<span class="err">El programa tiene errores: no se ejecuta.</span>'; return; }
        const lines = data.output.map(escapeHtml);
        if (data.runtime_error) lines.push(`<span class="err">${escapeHtml(data.runtime_error)}</span>`);
        outputBox.innerHTML = lines.length ? lines.join("\n") : '<span class="muted">(sin salida)</span>';
      }).catch((err) => { outputBox.innerHTML = '<span class="err">error de conexión</span>'; console.error(err); });
  }

  function render(data) {
    clearMarks();
    const n = data.errors.length;
    status.textContent = n ? `✘ ${n} error(es)` : "✔ sin errores";
    status.className = "status " + (n ? "bad" : "ok");
    errCount.textContent = n; errCount.className = "badge" + (n ? "" : " zero");

    errList.innerHTML = "";
    if (!n) { const li = document.createElement("li"); li.className = "empty"; li.textContent = "El programa es sintáctica y semánticamente correcto."; errList.appendChild(li); }
    data.errors.forEach((e) => {
      const li = document.createElement("li"); li.className = e.phase;
      li.innerHTML = `<span class="pos">${e.line}:${e.column}</span>${e.phase === "syntax" ? "[sintaxis] " : ""}${escapeHtml(e.message)}`;
      li.addEventListener("click", () => { editor.setCursor({ line: e.line - 1, ch: e.column }); editor.focus(); });
      errList.appendChild(li);
      if (e.line > 0) {
        editor.addLineClass(e.line - 1, "background", "error-line");
        const marker = document.createElement("span"); marker.className = "error-gutter"; marker.textContent = "●"; marker.title = e.message;
        editor.setGutterMarker(e.line - 1, "error-gutter", marker);
        const from = { line: e.line - 1, ch: e.column }, to = { line: e.line - 1, ch: e.column + 1 };
        markers.push(editor.markText(from, to, { className: "cm-error", title: e.message }));
      }
    });

    symBody.innerHTML = "";
    data.symbols.forEach((s) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${escapeHtml(s.scope)}</td><td>${escapeHtml(s.name)}</td><td class="kind-${s.kind}">${s.kind}</td>` +
        `<td>${escapeHtml(s.type)}</td><td>${s.line}</td><td>${s.offset}</td><td>${escapeHtml(s.extra || "")}</td>`;
      symBody.appendChild(tr);
    });

    treeBox.innerHTML = ""; treeBox.appendChild(buildTree(data.tree));
  }

  function buildTree(node) {
    const ul = document.createElement("ul"); ul.appendChild(buildNode(node)); return ul;
  }
  function buildNode(node) {
    const li = document.createElement("li");
    const span = document.createElement("span"); span.className = "node " + node.kind;
    const hasKids = node.children && node.children.length;
    span.innerHTML = `<span class="toggle">${hasKids ? "▾" : "·"}</span>` +
      (node.kind === "token" ? `<span class="token">'${escapeHtml(node.name)}'</span>` : `<span class="rule">${node.name}</span>`) +
      (node.type ? `<span class="type">${escapeHtml(node.type)}</span>` : "");
    span.addEventListener("click", (ev) => { ev.stopPropagation(); if (hasKids) { li.classList.toggle("collapsed"); span.querySelector(".toggle").textContent = li.classList.contains("collapsed") ? "▸" : "▾"; } if (node.line) editor.setCursor({ line: node.line - 1, ch: node.column || 0 }); });
    li.appendChild(span);
    if (hasKids) { const ul = document.createElement("ul"); node.children.forEach((c) => ul.appendChild(buildNode(c))); li.appendChild(ul); }
    return li;
  }

  $("svg").addEventListener("click", () => {
    fetch("/api/tree.svg", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source: editor.getValue() }) })
      .then(async (r) => {
        if (!r.ok) { const j = await r.json(); alert(j.error || "No se pudo generar el SVG"); return; }
        const blob = await r.blob(); window.open(URL.createObjectURL(blob), "_blank");
      });
  });

  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  $("run").addEventListener("click", run);
  $("exec").addEventListener("click", execute);
  $("mars").addEventListener("click", executeMars);
  editor.on("change", () => { clearOutput(); if (!$("live").checked) return; clearTimeout(timer); timer = setTimeout(run, 500); });
  clearOutput();
  run();
})();
