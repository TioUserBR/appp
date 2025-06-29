import os
import json
import hashlib
import requests
from flask import Flask, request, redirect, render_template, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'flavin'

# Configuração do banco PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "postgresql://useriste:9ylsskEKumh0EAk62o4sjJs98Ukcfog2@dpg-d1g9mn2li9vc73adief0-a/dbsite_nmqc")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modelos
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(80), unique=True, nullable=False)
    senha = db.Column(db.String(256), nullable=False)

class Conteudo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200))
    ano = db.Column(db.Integer)
    genero = db.Column(db.String(300))
    sinopse = db.Column(db.Text)
    banner = db.Column(db.String(300))
    tipo = db.Column(db.String(20))  # filme ou serie
    temporadas = db.Column(db.Integer, default=0)

class Temporada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    serie_id = db.Column(db.Integer, db.ForeignKey('conteudo.id', ondelete='CASCADE'))
    numero = db.Column(db.Integer)

class Episodio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    temporada_id = db.Column(db.Integer, db.ForeignKey('temporada.id', ondelete='CASCADE'))
    numero = db.Column(db.Integer)
    nome = db.Column(db.String(200))
    sinopse = db.Column(db.Text)
    capa = db.Column(db.String(200))

# Utils
CONFIG_FILE = 'config.json'

def salvar_tmdb_key(key):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"tmdb_api_key": key}, f)

def carregar_tmdb_key():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f).get('tmdb_api_key')
    return ""

# Decorador de login
def login_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'usuario' not in session:
            return redirect('/login')
        return func(*args, **kwargs)
    return wrapper

@app.route('/')
def home():
    return redirect('/dashboard') if 'usuario' in session else redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'usuario' in session:
        return redirect('/dashboard')

    erro = ''
    if request.method == 'POST':
        usuario = request.form['usuario']
        senha = request.form['senha']
        senha_hash = hashlib.sha256(senha.encode()).hexdigest()
        user = Usuario.query.filter_by(usuario=usuario, senha=senha_hash).first()
        if user:
            session['usuario'] = usuario
            return redirect('/dashboard')
        else:
            erro = 'Usuário ou senha inválidos.'
    return render_template('login.html', erro=erro)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if request.method == 'POST' and 'tmdb_key' in request.form:
        salvar_tmdb_key(request.form['tmdb_key'])
        return redirect('/dashboard')

    return render_template('dashboard.html',
        qtd_filmes=Conteudo.query.filter_by(tipo='filme').count(),
        qtd_series=Conteudo.query.filter_by(tipo='serie').count(),
        tmdb_key=carregar_tmdb_key()
    )

@app.route('/add_conteudo')
@login_required
def add_conteudo():
    return render_template('pesquisa.html')

@app.route('/pesquisar_conteudo', methods=['POST'])
@login_required
def pesquisar_conteudo():
    query = request.form.get('query')
    tipo = request.form.get('tipo')
    tmdb_key = carregar_tmdb_key()

    if tipo not in ['filme', 'serie']:
        return {"erro": "Tipo inválido"}, 400

    url = f"https://api.themoviedb.org/3/search/{'movie' if tipo == 'filme' else 'tv'}"
    r = requests.get(url, params={"api_key": tmdb_key, "language": "pt-BR", "query": query}).json()
    return r

@app.route('/salvar_conteudo', methods=['POST'])
@login_required
def salvar_conteudo():
    tmdb_id = request.form.get('tmdb_id')
    tipo = request.form.get('tipo')
    tmdb_key = carregar_tmdb_key()

    if not tmdb_id:
        return "ID inválido", 400

    url = f"https://api.themoviedb.org/3/{'movie' if tipo == 'filme' else 'tv'}/{tmdb_id}"
    data = requests.get(url, params={"api_key": tmdb_key, "language": "pt-BR"}).json()

    conteudo = Conteudo(
        titulo=data.get('title') or data.get('name'),
        ano=int((data.get('release_date') or data.get('first_air_date') or '0')[:4]),
        genero=', '.join([g['name'] for g in data.get('genres', [])]),
        sinopse=data.get('overview'),
        banner=data.get('backdrop_path') or data.get('poster_path'),
        tipo=tipo,
        temporadas=data.get('number_of_seasons') if tipo == 'serie' else 0
    )
    db.session.add(conteudo)
    db.session.commit()
    return redirect('/dashboard')

@app.route('/add_temporadas', methods=['GET', 'POST'])
@login_required
def add_temporadas():
    if request.method == 'POST':
        serie_id = request.form.get('serie_id')
        conteudo = Conteudo.query.get(serie_id)
        tmdb_key = carregar_tmdb_key()

        search = requests.get("https://api.themoviedb.org/3/search/tv", params={
            "api_key": tmdb_key,
            "language": "pt-BR",
            "query": conteudo.titulo
        }).json()

        tmdb_id = search.get("results", [{}])[0].get("id")
        detalhes = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}", params={
            "api_key": tmdb_key, "language": "pt-BR"
        }).json()

        for t in range(1, detalhes.get("number_of_seasons", 0) + 1):
            temp = Temporada(serie_id=serie_id, numero=t)
            db.session.add(temp)
            db.session.flush()

            eps = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{t}", params={
                "api_key": tmdb_key, "language": "pt-BR"
            }).json()
            for ep in eps.get('episodes', []):
                db.session.add(Episodio(
                    temporada_id=temp.id,
                    numero=ep.get("episode_number"),
                    nome=ep.get("name"),
                    sinopse=ep.get("overview"),
                    capa=ep.get("still_path") or ''
                ))
        db.session.commit()
        return redirect('/dashboard')

    series = Conteudo.query.filter_by(tipo='serie').all()
    return render_template('add_temporadas.html', series=series)

@app.route('/api/filmes')
@login_required
def api_filmes():
    filmes = Conteudo.query.filter_by(tipo='filme').all()
    return jsonify([{
        "nome": f.titulo,
        "capa": f"/img/{f.banner}",
        "banner": f"/img/{f.banner}",
        "genero": f.genero,
        "ano": f.ano,
        "sinopse": f.sinopse
    } for f in filmes])

@app.route('/api/series')
@login_required
def api_series():
    series = Conteudo.query.filter_by(tipo='serie').all()
    return jsonify([{
        "id": s.id,
        "nome": s.titulo,
        "banner": f"/img/{s.banner}",
        "genero": s.genero,
        "sinopse": s.sinopse,
        "ano": s.ano,
        "temporadas": s.temporadas
    } for s in series])

@app.route('/api/serie/<int:serie_id>')
@login_required
def api_serie_detalhada(serie_id):
    conteudo = Conteudo.query.get(serie_id)
    if not conteudo or conteudo.tipo != 'serie':
        return jsonify({"erro": "Série não encontrada"}), 404

    temporadas_data = []
    for temp in Temporada.query.filter_by(serie_id=serie_id).all():
        episodios_data = [{
            "numero": ep.numero,
            "nome": ep.nome,
            "sinopse": ep.sinopse,
            "capa": f"/img/{ep.capa}" if ep.capa else ""
        } for ep in Episodio.query.filter_by(temporada_id=temp.id).all()]
        temporadas_data.append({
            "temporada": temp.numero,
            "episodios": episodios_data
        })

    return jsonify({
        "id": conteudo.id,
        "nome": conteudo.titulo,
        "banner": f"/img/{conteudo.banner}",
        "genero": conteudo.genero,
        "ano": conteudo.ano,
        "sinopse": conteudo.sinopse,
        "temporadas": temporadas_data
    })

@app.route('/img/<path:path>')
def img(path):
    url = f'https://image.tmdb.org/t/p/w500/{path}'
    r = requests.get(url)
    if r.status_code == 200:
        return send_file(BytesIO(r.content), mimetype='image/jpeg')
    return "Imagem não encontrada", 404

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
    
