import json
import os
import sqlite3
import hashlib
from flask import Flask, render_template, request, redirect, session, jsonify, send_file
import requests
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'flavin'  # Troque por algo seguro

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE,
            senha TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS conteudos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            ano INTEGER,
            genero TEXT,
            sinopse TEXT,
            banner TEXT,
            tipo TEXT,
            temporadas INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS temporadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serie_id INTEGER,
            numero INTEGER,
            FOREIGN KEY (serie_id) REFERENCES conteudos(id) ON DELETE CASCADE
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS episodios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temporada_id INTEGER,
            numero INTEGER,
            nome TEXT,
            sinopse TEXT,
            capa TEXT,
            FOREIGN KEY (temporada_id) REFERENCES temporadas(id) ON DELETE CASCADE
        )
    ''')

    senha_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute("SELECT * FROM usuarios WHERE usuario = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO usuarios (usuario, senha) VALUES (?, ?)", ('admin', senha_hash))

    conn.commit()
    conn.close()

CONFIG_FILE = 'config.json'

def salvar_tmdb_key(key):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"tmdb_api_key": key}, f)

def carregar_tmdb_key():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f).get("tmdb_api_key")
    return ""

def login_required(f):
    def wrapper(*args, **kwargs):
        if 'usuario' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/')
def home():
    if 'usuario' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/login', methods=['GET','POST'])
def login():
    if 'usuario' in session:
        return redirect('/dashboard')
    erro = ''
    if request.method == 'POST':
        usuario = request.form['usuario']
        senha = request.form['senha']
        senha_hash = hashlib.sha256(senha.encode()).hexdigest()
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT * FROM usuarios WHERE usuario=? AND senha=?", (usuario, senha_hash))
        if c.fetchone():
            session['usuario'] = usuario
            conn.close()
            return redirect('/dashboard')
        erro = 'Usuário ou senha inválidos.'
        conn.close()
    return render_template('login.html', erro=erro)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard', methods=['GET','POST'])
@login_required
def dashboard():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM conteudos WHERE tipo='filme'")
    qtd_filmes = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM conteudos WHERE tipo='serie'")
    qtd_series = c.fetchone()[0]

    if request.method == 'POST' and 'tmdb_key' in request.form:
        salvar_tmdb_key(request.form['tmdb_key'])
        return redirect('/dashboard')

    tmdb_key = carregar_tmdb_key()
    conn.close()
    return render_template('dashboard.html', qtd_filmes=qtd_filmes, qtd_series=qtd_series, tmdb_key=tmdb_key)

@app.route('/add_conteudo')
@login_required
def add_conteudo():
    if not carregar_tmdb_key():
        return redirect('/dashboard')
    return render_template('pesquisa.html')

@app.route('/pesquisar_conteudo', methods=['POST'])
@login_required
def pesquisar_conteudo():
    tmdb_key = carregar_tmdb_key()
    if not tmdb_key:
        return {"error":"API Key não configurada"}, 400

    query = request.form.get('query')
    tipo = request.form.get('tipo')
    if not query or tipo not in ['filme','serie']:
        return {"error":"Dados inválidos"}, 400

    url_base = "https://api.themoviedb.org/3/search/"
    url = f"{url_base}movie" if tipo=='filme' else f"{url_base}tv"
    params = {"api_key": tmdb_key, "language": "pt-BR", "query": query, "page":1, "include_adult":False}
    r = requests.get(url, params=params)
    return r.json()

@app.route('/salvar_conteudo', methods=['POST'])
@login_required
def salvar_conteudo():
    tmdb_key = carregar_tmdb_key()
    if not tmdb_key:
        return {"erro":"API Key não configurada"}, 400

    titulo = request.form.get('titulo')
    ano = request.form.get('ano')
    tipo = request.form.get('tipo')
    tmdb_id = request.form.get('tmdb_id')

    if tipo not in ['filme','serie'] or not tmdb_id:
        return {"erro":"Dados inválidos"}, 400

    url_base = "https://api.themoviedb.org/3"
    url = f"{url_base}/movie/{tmdb_id}" if tipo == 'filme' else f"{url_base}/tv/{tmdb_id}"
    r = requests.get(url, params={"api_key": tmdb_key, "language": "pt-BR"})
    if r.status_code != 200:
        return {"erro":"Falha ao obter dados do TMDb"}, 500
    dados = r.json()

    generos = ', '.join(g['name'] for g in dados.get('genres', []))
    sinopse = dados.get('overview', '')
    banner_path = dados.get('backdrop_path') or dados.get('poster_path') or ''
    banner_url = f"/img/{banner_path.lstrip('/')}" if banner_path else ''

    temporadas = dados.get('number_of_seasons', 0) if tipo == 'serie' else 0

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('INSERT INTO conteudos (titulo, ano, genero, sinopse, banner, tipo, temporadas) VALUES (?, ?, ?, ?, ?, ?, ?)',
              (titulo, ano, generos, sinopse, banner_url, tipo, temporadas))
    conn.commit()
    conn.close()

    return redirect('/dashboard')

@app.route('/api/filmes')
@login_required
def api_filmes():
    page = request.args.get('page', 1, type=int)
    limit = 50
    offset = (page - 1) * limit

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM conteudos WHERE tipo='filme'")
    total = c.fetchone()[0]

    c.execute('''
        SELECT titulo, banner, banner, genero, ano, sinopse
        FROM conteudos
        WHERE tipo='filme'
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    filmes = c.fetchall()
    conn.close()

    lista = []
    for f in filmes:
        lista.append({
            "nome": f[0],
            "capa": f[1],
            "banner": f[2],
            "genero": f[3],
            "ano": f[4],
            "sinopse": f[5]
        })

    total_pages = (total + limit - 1) // limit
    next_page = page + 1 if page < total_pages else None

    return jsonify({
        "pagina_atual": page,
        "total_paginas": total_pages,
        "total_filmes": total,
        "filmes": lista,
        "proxima_pagina": f"/api/filmes?page={next_page}" if next_page else None
    })

@app.route('/api/series')
@login_required
def api_series():
    page = request.args.get('page', 1, type=int)
    limit = 50
    offset = (page - 1) * limit

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM conteudos WHERE tipo='serie'")
    total = c.fetchone()[0]

    c.execute('''
        SELECT id, titulo, banner, genero, sinopse, ano, temporadas
        FROM conteudos
        WHERE tipo='serie'
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    series = c.fetchall()
    conn.close()

    lista = []
    for s in series:
        lista.append({
            "id": s[0],
            "nome": s[1],
            "banner": f"/img/{s[2].lstrip('/')}",
            "genero": s[3],
            "sinopse": s[4],
            "ano": s[5],
            "temporadas": s[6] or 0
        })

    total_pages = (total + limit -1) // limit
    next_page = page +1 if page < total_pages else None

    return jsonify({
        "pagina_atual": page,
        "total_paginas": total_pages,
        "total_series": total,
        "series": lista,
        "proxima_pagina": f"/api/series?page={next_page}" if next_page else None
    })

@app.route('/add_temporadas', methods=['GET', 'POST'])
@login_required
def add_temporadas():
    conn = sqlite3.connect('database.db')
    conn.execute('PRAGMA foreign_keys = ON')
    c = conn.cursor()

    if request.method == 'POST':
        serie_id = request.form.get('serie_id')
        tmdb_key = carregar_tmdb_key()

        c.execute("SELECT titulo FROM conteudos WHERE id=? AND tipo='serie'", (serie_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return "Série não encontrada", 404

        titulo = row[0]

        url_busca = "https://api.themoviedb.org/3/search/tv"
        params = {"api_key": tmdb_key, "language": "pt-BR", "query": titulo}
        r = requests.get(url_busca, params=params).json()
        resultados = r.get("results", [])
        if not resultados:
            conn.close()
            return "Série não encontrada no TMDb", 404

        tmdb_id = resultados[0]["id"]

        detalhes = requests.get(
            f"https://api.themoviedb.org/3/tv/{tmdb_id}",
            params={"api_key": tmdb_key, "language": "pt-BR"}
        ).json()

        num_temporadas = detalhes.get("number_of_seasons", 0)

        try:
            for temporada in range(1, num_temporadas + 1):
                c.execute("INSERT INTO temporadas (serie_id, numero) VALUES (?, ?)", (serie_id, temporada))
                temporada_id = c.lastrowid

                eps = requests.get(
                    f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{temporada}",
                    params={"api_key": tmdb_key, "language": "pt-BR"}
                ).json()

                for ep in eps.get("episodes", []):
                    c.execute('''
                        INSERT INTO episodios (temporada_id, numero, nome, sinopse, capa)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        temporada_id,
                        ep.get("episode_number"),
                        ep.get("name"),
                        ep.get("overview"),
                        ep.get("still_path") or ''
                    ))
            c.execute("UPDATE conteudos SET temporadas=? WHERE id=?", (num_temporadas, serie_id))
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            conn.close()
            return f"Erro: {e}", 500

        conn.close()
        return redirect('/dashboard')

    c.execute("SELECT id, titulo FROM conteudos WHERE tipo='serie'")
    series = c.fetchall()
    conn.close()
    return render_template('add_temporadas.html', series=series)

@app.route('/api/serie/<int:serie_id>')
@login_required
def api_serie_detalhada(serie_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute('''
        SELECT id, titulo, banner, genero, sinopse, ano, temporadas
        FROM conteudos
        WHERE id = ? AND tipo = 'serie'
    ''', (serie_id,))
    serie = c.fetchone()
    if not serie:
        conn.close()
        return jsonify({"erro": "Série não encontrada"}), 404

    serie_info = {
        "id": serie[0],
        "nome": serie[1],
        "banner": f"/img/{serie[2].lstrip('/')}",
        "genero": serie[3],
        "sinopse": serie[4],
        "ano": serie[5],
        "temporadas": []
    }

    c.execute("SELECT id, numero FROM temporadas WHERE serie_id = ? ORDER BY numero ASC", (serie_id,))
    temporadas = c.fetchall()

    for temp in temporadas:
        temporada_id, numero_temp = temp

        c.execute("""
            SELECT numero, nome, sinopse, capa FROM episodios WHERE temporada_id = ? ORDER BY numero ASC
        """, (temporada_id,))
        episodios = c.fetchall()

        eps_lista = []
        for ep in episodios:
            eps_lista.append({
                "numero": ep[0],
                "nome": ep[1],
                "sinopse": ep[2],
                "capa": f"/img_eps/{ep[3].lstrip('/')}" if ep[3] else ""
            })

        serie_info["temporadas"].append({
            "numero": numero_temp,
            "episodios": eps_lista
        })

    conn.close()
    return jsonify(serie_info)

@app.route('/img/<path:poster_path>')
def obter_imagem_tmdb(poster_path):
    url = f'https://image.tmdb.org/t/p/w500/{poster_path}'
    r = requests.get(url)
    if r.status_code == 200:
        return send_file(BytesIO(r.content), mimetype='image/jpeg')
    return "Imagem não encontrada", 404

@app.route('/img_eps/<path:still_path>')
def imagem_episodio(still_path):
    url = f'https://image.tmdb.org/t/p/w500/{still_path}'
    r = requests.get(url)
    if r.status_code == 200:
        return send_file(BytesIO(r.content), mimetype='image/jpeg')
    return "Imagem não encontrada", 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
