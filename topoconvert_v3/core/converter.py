"""
Motor de conversão topográfica — TopoConvert v3
Lê: CSV estação total, LandXML, TXT GNSS RTK
Exporta: LandXML (CogoPoints + TIN) + XYZ + CSV Civil 3D
"""
import csv, io, re, zipfile, json
import xml.etree.ElementTree as ET
from xml.dom import minidom
from dataclasses import dataclass
from typing import List, Optional

try:
    from scipy.spatial import Delaunay as ScipyDelaunay
    import numpy as np
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


@dataclass
class Ponto:
    numero: str
    norte:  float
    leste:  float
    cota:   float
    descricao: str = ""


# ─── Detecção de separador ────────────────────────────────────
def _sep(texto: str) -> str:
    linha = texto.split("\n")[0]
    for s in [";", "\t", ","]:
        if linha.count(s) >= 2:
            return s
    return ","


# ─── Detecção automática de colunas ──────────────────────────
def detectar_mapeamento(linhas_dados: list) -> dict:
    """Detecta automaticamente qual coluna é cada campo topográfico."""
    am = linhas_dados[:6]
    nc = max(len(r) for r in am)
    stats = []
    for c in range(nc):
        vals = [float(r[c].replace(",",".")) for r in am if c < len(r) and _is_num(r[c])]
        media = sum(vals)/len(vals) if vals else 0
        # Verifica se parece inteiro sequencial (ponto)
        is_seq = len(vals) > 0 and all(v == int(v) for v in vals) and media < 50000
        stats.append({"c": c, "media": media, "npct": len(vals)/len(am), "seq": is_seq})

    found = {}

    # 1. Descrição: colunas com < 50% de números (texto)
    for s in stats:
        if s["npct"] < 0.5 and "desc" not in found:
            found["desc"] = s["c"]

    # 2. Norte: valor entre 3M e 10M (UTM Brasil)
    for s in stats:
        if 3e6 < s["media"] < 1e7 and "norte" not in found:
            found["norte"] = s["c"]

    # 3. Leste: valor entre 100k e 900k (UTM zona)
    for s in stats:
        if 1e5 < s["media"] < 9e5 and "leste" not in found:
            found["leste"] = s["c"]

    # 4. Ponto: inteiros sequenciais pequenos (1, 2, 3...)
    usadas = set(found.values())
    for s in stats:
        if s["c"] not in usadas and s["seq"] and s["media"] < 100000 and "ponto" not in found:
            found["ponto"] = s["c"]

    # 5. Cota: numérico restante com valor entre 0 e 5000
    usadas = set(found.values())
    cotas = [s for s in stats if s["c"] not in usadas and s["npct"] > .8 and 0 < s["media"] < 5000]
    if cotas and "cota" not in found:
        cotas.sort(key=lambda s: abs(s["media"] - 500))
        found["cota"] = cotas[0]["c"]

    # 6. Ponto fallback: qualquer numérico restante pequeno
    if "ponto" not in found:
        usadas = set(found.values())
        rest = [s for s in stats if s["c"] not in usadas and s["npct"] > .8 and s["media"] < 100000]
        if rest:
            rest.sort(key=lambda s: s["media"])
            found["ponto"] = rest[0]["c"]

    inv = {v: k for k, v in found.items()}
    return {c: inv.get(c, "ignore") for c in range(nc)}


def _is_num(s: str) -> bool:
    try:
        float(s.strip().replace(",","."))
        return True
    except:
        return False


# ─── Leitores ─────────────────────────────────────────────────
def ler_csv(texto: str, mapeamento: Optional[dict] = None) -> List[Ponto]:
    sep = _sep(texto)
    linhas = texto.strip().splitlines()

    # Detecta cabeçalho
    inicio = 0
    cols0 = linhas[0].split(sep)
    if not _is_num(cols0[1] if len(cols0) > 1 else cols0[0]):
        inicio = 1

    dados = [l.split(sep) for l in linhas[inicio:] if l.strip()]
    dados = [[c.strip() for c in r] for r in dados if len(r) >= 3]

    if mapeamento is None:
        mapeamento = detectar_mapeamento(dados)

    def gi(campo):
        for c, f in mapeamento.items():
            if f == campo:
                return int(c)
        return None

    pi, ni, ei, zi, di = gi("ponto"), gi("norte"), gi("leste"), gi("cota"), gi("desc")
    pontos = []
    for i, r in enumerate(dados):
        try:
            pontos.append(Ponto(
                numero   = r[pi].strip() if pi is not None and pi < len(r) else str(i+1),
                norte    = float(r[ni].replace(",",".")) if ni is not None else 0.0,
                leste    = float(r[ei].replace(",",".")) if ei is not None else 0.0,
                cota     = float(r[zi].replace(",",".")) if zi is not None else 0.0,
                descricao= r[di].strip() if di is not None and di < len(r) else "",
            ))
        except (ValueError, IndexError):
            continue
    return pontos


def ler_landxml(texto: str) -> List[Ponto]:
    try:
        root = ET.fromstring(texto)
    except ET.ParseError as e:
        raise ValueError(f"LandXML inválido: {e}")
    ns = {"lx": "http://www.landxml.org/schema/LandXML-1.2"}
    pts = root.findall(".//lx:CgPoint", ns) or root.findall(".//CgPoint")
    pontos = []
    for pt in pts:
        nome = pt.get("name", pt.get("oID", str(len(pontos)+1)))
        desc = pt.get("desc","")
        coords = (pt.text or "").strip().split()
        if len(coords) >= 2:
            pontos.append(Ponto(
                numero=nome, norte=float(coords[0]),
                leste=float(coords[1]),
                cota=float(coords[2]) if len(coords)>2 else 0.0,
                descricao=desc,
            ))
    return pontos


def ler_gnss(texto: str) -> List[Ponto]:
    return ler_csv(texto)  # mesmo parser, detecção automática


def detectar_formato(texto: str, nome: str) -> str:
    n = nome.lower()
    if n.endswith(".xml") or n.endswith(".landxml"):
        return "landxml"
    if "<landxml" in texto[:200].lower() or "<?xml" in texto[:10].lower():
        return "landxml"
    return "csv"


def ler(texto: str, nome: str, mapeamento=None) -> List[Ponto]:
    fmt = detectar_formato(texto, nome)
    if fmt == "landxml":
        return ler_landxml(texto)
    return ler_csv(texto, mapeamento)


# ─── Triangulação Delaunay ────────────────────────────────────
def triangular(pontos: List[Ponto]):
    if len(pontos) < 3:
        return []
    if HAS_SCIPY:
        pts = np.array([[p.leste, p.norte] for p in pontos])
        tri = ScipyDelaunay(pts)
        return tri.simplices.tolist()
    # fallback Bowyer-Watson básico
    return _bowyer_watson(pontos)


def _bowyer_watson(pontos):
    pts = [(p.leste, p.norte) for p in pontos]
    n = len(pts)
    min_x = min(p[0] for p in pts); max_x = max(p[0] for p in pts)
    min_y = min(p[1] for p in pts); max_y = max(p[1] for p in pts)
    d = max(max_x-min_x, max_y-min_y)*10
    sup = [(min_x-d, min_y-d),(min_x+d/2, max_y+d),(max_x+d, min_y-d)]
    all_pts = pts + sup
    tris = [(n, n+1, n+2)]
    for i, p in enumerate(pts):
        bad = []
        for t in tris:
            cc = _cc(all_pts[t[0]], all_pts[t[1]], all_pts[t[2]])
            if cc and (p[0]-cc[0])**2+(p[1]-cc[1])**2 < cc[2]:
                bad.append(t)
        bnd = {}
        for t in bad:
            for e in [(t[0],t[1]),(t[1],t[2]),(t[2],t[0])]:
                k = tuple(sorted(e)); bnd[k]=bnd.get(k,0)+1
        tris = [t for t in tris if t not in bad]
        for e,c in bnd.items():
            if c==1: tris.append((e[0],e[1],i))
    return [[a,b,c] for a,b,c in tris if a<n and b<n and c<n]


def _cc(p1,p2,p3):
    ax,ay=p1; bx,by=p2; cx,cy=p3
    D=2*(ax*(by-cy)+bx*(cy-ay)+cx*(ay-by))
    if abs(D)<1e-10: return None
    ux=((ax**2+ay**2)*(by-cy)+(bx**2+by**2)*(cy-ay)+(cx**2+cy**2)*(ay-by))/D
    uy=((ax**2+ay**2)*(cx-bx)+(bx**2+by**2)*(ax-cx)+(cx**2+cy**2)*(bx-ax))/D
    return ux,uy,(ax-ux)**2+(ay-uy)**2


# ─── Exportadores ─────────────────────────────────────────────
def exportar_landxml(pontos: List[Ponto], nome="Projeto") -> str:
    root = ET.Element("LandXML",{
        "xmlns":"http://www.landxml.org/schema/LandXML-1.2",
        "version":"1.2","language":"Portuguese",
    })
    ET.SubElement(root,"Project",{"name":nome})

    cg = ET.SubElement(root,"CgPoints",{"name":"Levantamento"})
    for p in pontos:
        el = ET.SubElement(cg,"CgPoint",{"name":str(p.numero)})
        if p.descricao: el.set("desc",p.descricao)
        el.text = f"{p.norte:.4f} {p.leste:.4f} {p.cota:.4f}"

    surfs = ET.SubElement(root,"Surfaces")
    surf  = ET.SubElement(surfs,"Surface",{"name":"Terreno Natural"})
    defn  = ET.SubElement(surf,"Definition",{"surfType":"TIN"})
    pnts  = ET.SubElement(defn,"Pnts")
    for i,p in enumerate(pontos,1):
        pe = ET.SubElement(pnts,"P",{"id":str(i)})
        pe.text = f"{p.norte:.4f} {p.leste:.4f} {p.cota:.4f}"

    tris = triangular(pontos)
    faces = ET.SubElement(defn,"Faces")
    for t in tris:
        a,b,c = t[0]+1, t[1]+1, t[2]+1
        p0,p1,p2 = pontos[t[0]],pontos[t[1]],pontos[t[2]]
        cz = (p1.leste-p0.leste)*(p2.norte-p0.norte)-(p1.norte-p0.norte)*(p2.leste-p0.leste)
        if cz < 0: b,c = c,b
        fe = ET.SubElement(faces,"F"); fe.text=f"{a} {b} {c}"

    raw = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(f'<?xml version="1.0" encoding="UTF-8"?>{raw}')
    return dom.toprettyxml(indent="  ").replace('<?xml version="1.0" ?>','<?xml version="1.0" encoding="UTF-8"?>')


def exportar_xyz(pontos: List[Ponto]) -> str:
    linhas = ["X Y Z Intensity"]
    for p in pontos:
        linhas.append(f"{p.leste:.4f} {p.norte:.4f} {p.cota:.4f} 0")
    return "\n".join(linhas)


def exportar_csv(pontos: List[Ponto]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Ponto","Norte","Leste","Elevacao","Descricao"])
    for p in pontos:
        w.writerow([p.numero,f"{p.norte:.4f}",f"{p.leste:.4f}",f"{p.cota:.4f}",p.descricao])
    return buf.getvalue()


def gerar_zip(pontos: List[Ponto], nome: str) -> bytes:
    safe = nome.replace(" ","_")
    buf = io.BytesIO()
    tris = triangular(pontos)
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{safe}_civil3d.xml",  exportar_landxml(pontos, nome))
        zf.writestr(f"{safe}_nuvem.xyz",    exportar_xyz(pontos))
        zf.writestr(f"{safe}_cogopoints.csv", exportar_csv(pontos))
        # metadados para o frontend
        meta = {"pontos": len(pontos), "triangulos": len(tris), "nome": nome}
        zf.writestr("_meta.json", json.dumps(meta))
    return buf.getvalue()
