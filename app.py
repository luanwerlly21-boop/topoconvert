"""
TopoConvert API v3 — Flask
Roda com: python app.py
"""
import os, json, csv, io, re
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response
import sys
sys.path.insert(0, os.path.dirname(__file__))
from core.converter import ler, detectar_mapeamento, detectar_formato, gerar_zip, _sep

app = Flask(__name__, static_folder="static")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# SERVIR FRONTEND
# ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/static/<path:p>")
def static_files(p):
    return send_from_directory("static", p)


# ─────────────────────────────────────────────────────────────
# DETECTAR COLUNAS — retorna prévia para o frontend mapear
# ─────────────────────────────────────────────────────────────
@app.route("/api/detectar", methods=["POST"])
def detectar():
    f = request.files.get("arquivo")
    texto = request.form.get("texto","")

    if f:
        raw = f.read()
        for enc in ("utf-8","latin-1","cp1252"):
            try: texto = raw.decode(enc); break
            except: pass
        nome = f.filename
    else:
        nome = "dados.csv"

    if not texto.strip():
        return jsonify({"erro": "Arquivo vazio"}), 400

    sep = _sep(texto)
    linhas = texto.strip().splitlines()
    primeira = linhas[0].split(sep)

    # Detecta cabeçalho
    def is_num(s):
        try: float(s.strip().replace(",",".")); return True
        except: return False

    tem_cab = not is_num(primeira[1] if len(primeira)>1 else primeira[0])
    cabecalho = [c.strip() for c in primeira] if tem_cab else [f"Col {i+1}" for i in range(len(primeira))]
    dados = [l.split(sep) for l in linhas[(1 if tem_cab else 0):] if l.strip()]
    dados = [[c.strip() for c in r] for r in dados if len(r)>=3]

    if not dados:
        return jsonify({"erro": "Nenhum dado encontrado"}), 400

    mapeamento = detectar_mapeamento(dados)
    amostra = [r for r in dados[:8]]

    return jsonify({
        "cabecalho": cabecalho,
        "amostra": amostra,
        "mapeamento": mapeamento,
        "total_linhas": len(dados),
        "separador": sep,
        "nome": nome,
    })


# ─────────────────────────────────────────────────────────────
# CONVERTER — recebe arquivo + mapeamento, retorna ZIP
# ─────────────────────────────────────────────────────────────
@app.route("/api/converter", methods=["POST"])
def converter():
    f    = request.files.get("arquivo")
    nome = request.form.get("nome_projeto", "Projeto")
    email= request.form.get("email","").strip()
    mapa_json = request.form.get("mapeamento","")

    # Lê arquivo
    if f:
        raw = f.read()
        texto = ""
        for enc in ("utf-8","latin-1","cp1252"):
            try: texto = raw.decode(enc); break
            except: pass
        nome_arq = f.filename
    else:
        texto = request.form.get("texto","")
        nome_arq = "dados.csv"

    if not texto.strip():
        return jsonify({"erro": "Arquivo vazio"}), 400

    # Mapeamento de colunas (vem do frontend)
    mapeamento = None
    if mapa_json:
        try:
            mapeamento = {int(k): v for k,v in json.loads(mapa_json).items()}
        except: pass

    try:
        pontos = ler(texto, nome_arq, mapeamento)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 422

    if not pontos:
        return jsonify({"erro": "Nenhum ponto encontrado. Verifique o mapeamento de colunas."}), 422

    # Salva email + metadados
    if email:
        _salvar_lead(email, nome, len(pontos), nome_arq)

    # Gera ZIP
    zip_bytes = gerar_zip(pontos, nome)
    safe = nome.replace(" ","_")

    return Response(
        zip_bytes,
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}_civil3d.zip"',
            "X-Pontos": str(len(pontos)),
        }
    )


# ─────────────────────────────────────────────────────────────
# CAPTURAR EMAIL (antes do download)
# ─────────────────────────────────────────────────────────────
@app.route("/api/email", methods=["POST"])
def capturar_email():
    data = request.get_json() or {}
    email = data.get("email","").strip()
    nome  = data.get("nome","").strip()

    if not email or "@" not in email:
        return jsonify({"erro": "Email inválido"}), 400

    _salvar_lead(email, nome, 0, "")
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# FEEDBACK
# ─────────────────────────────────────────────────────────────
@app.route("/api/feedback", methods=["POST"])
def feedback():
    data = request.get_json() or {}
    path = os.path.join(DATA_DIR, "feedback.csv")
    novo = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["data","email","equipamento","converteu","nota","comentario"])
        w.writerow([
            datetime.now().isoformat(),
            data.get("email",""),
            data.get("equipamento",""),
            data.get("converteu",""),
            data.get("nota",""),
            data.get("comentario",""),
        ])
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# ADMIN — ver leads e feedback (protegido por token)
# ─────────────────────────────────────────────────────────────
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "topo2025")

@app.route("/admin/leads")
def admin_leads():
    if request.args.get("token") != ADMIN_TOKEN:
        return "Não autorizado", 401
    path = os.path.join(DATA_DIR, "leads.csv")
    if not os.path.exists(path):
        return "Sem dados ainda"
    with open(path, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/plain")

@app.route("/admin/feedback")
def admin_feedback():
    if request.args.get("token") != ADMIN_TOKEN:
        return "Não autorizado", 401
    path = os.path.join(DATA_DIR, "feedback.csv")
    if not os.path.exists(path):
        return "Sem feedback ainda"
    with open(path, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/plain")


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _salvar_lead(email, nome_proj, n_pontos, nome_arq):
    path = os.path.join(DATA_DIR, "leads.csv")
    novo = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["data","email","projeto","pontos","arquivo"])
        w.writerow([datetime.now().isoformat(), email, nome_proj, n_pontos, nome_arq])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    print(f"TopoConvert rodando em http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
