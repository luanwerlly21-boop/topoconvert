# TopoConvert v3 — Deploy em 15 minutos

## Rodar localmente
```bash
pip install flask scipy numpy
python app.py
# Abre: http://localhost:5000
```

## Deploy no Railway (recomendado — gratuito para começar)

1. Crie conta em railway.app
2. "New Project" → "Deploy from GitHub repo"
3. Suba este projeto num repositório GitHub
4. Railway detecta o Procfile automaticamente
5. Em 2 minutos você tem uma URL pública

### Variáveis de ambiente (Railway → Variables)
```
ADMIN_TOKEN=suasenhasecreta123
FLASK_ENV=production
PORT=5000
```

## Ver os leads e feedback
```
https://seuapp.railway.app/admin/leads?token=suasenhasecreta123
https://seuapp.railway.app/admin/feedback?token=suasenhasecreta123
```

## Estrutura do projeto
```
topoconvert_v3/
├── app.py              ← API Flask
├── core/
│   └── converter.py    ← Motor de conversão
├── static/
│   └── index.html      ← Frontend completo
├── data/               ← leads.csv e feedback.csv (criado automaticamente)
├── requirements.txt
└── Procfile
```

## Enviar para os 10 testadores
Mensagem sugerida:
"Olá! Estou testando um conversor de arquivos topográficos para Civil 3D.
Funciona com CSV de estação total, GNSS e LandXML — detecta as colunas
automaticamente e entrega LandXML + nuvem de pontos + superfície TIN num ZIP.
Pode testar com um arquivo real seu? [LINK]
Qualquer feedback é muito bem-vindo!"
