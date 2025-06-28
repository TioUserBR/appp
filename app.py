import json
import os
import sqlite3
import hashlib
from flask import Flask, render_template, request, redirect, session, jsonify, send_file
import requests
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'uma-chave-secreta-muito-segura'  # Troque para algo forte em produção

# Inicializa banco de dados e cria tabelas se não existirem
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # Usuários
    c.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE,
            senha TEXT
        )
    ''')

    # Conteúdos (filmes e séries)
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

    # Temporadas
    c.execute('''
        CREATE TABLE IF NOT EXISTS temporadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serie_id INTEGER,
            numero INTEGER,
            FOREIGN KEY (serie_id) REFERENCES conteudos(id) ON DELETE CASCADE
        )
    ''')

    # Episódios
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

    # Cria admin padrão se não existir
    senha_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute("SELECT * FROM usuarios WHERE usuario = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO usuarios (usuario, senha) VALUES (?, ?)", ('admin', senha_hash))

    conn.commit()
    conn.close()

# Chama a função para garantir que o banco e tabelas existam
init_db()

# Config do arquivo para salvar API key do TMDb
CONFIG_FILE = 'config.json'

def salvar_tmdb_key(key):
    config = {"tmdb_api_key": key}
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

def carregar_tmdb_key():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            config = json.load(f)
            return config.get('tmdb_api_key')
    return ""

# Decorador para rotas protegidas (login)
def login_required(func):
    def wrapper(*args, **kwargs):
        if 'usuario' not in session:
            return redirect('/login')
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# Rota para obter imagens do TMDb
@app.route('/img/<path:poster_path>')
def obter_imagem_tmdb(poster_path):
    url = f'https://image.tmdb.org/t/p/w500/{poster_path}'
    response = requests.get(url)
    if response.status_code == 200:
        return send_file(BytesIO(response.content), mimetype='image/jpeg')
    return "Imagem não encontrada", 404

# Página inicial
@app.route('/')
def home():
    if 'usuario' in session:
        return redirect('/dashboard')
    return redirect('/login')

# Login
@app.route('/login', methods=['GET', 'POST'])
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
        user = c.fetchone()
        conn.close()

        if user:
            session['usuario'] = usuario
            return redirect('/dashboard')
        else:
            erro = 'Usuário ou senha inválidos.'

    return render_template('login.html', erro=erro)

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# Dashboard principal
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM conteudos WHERE tipo='filme'")
    qtd_filmes = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM conteudos WHERE tipo='serie'")
    qtd_series = c.fetchone()[0]

    if request.method == 'POST' and 'tmdb_key' in request.form:
        key = request.form['tmdb_key']
        salvar_tmdb_key(key)
        return redirect('/dashboard')

    tmdb_key = carregar_tmdb_key()
    conn.close()

    return render_template('dashboard.html',
                           qtd_filmes=qtd_filmes,
                           qtd_series=qtd_series,
                           tmdb_key=tmdb_key)

# Gerenciar usuários
@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
def usuarios():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if request.method == 'POST':
        acao = request.form.get('acao')

        if acao == 'criar':
            novo_usuario = request.form.get('novo_usuario')
            nova_senha = hashlib.sha256(request.form.get('nova_senha').encode()).hexdigest()
            try:
                c.execute("INSERT INTO usuarios (usuario, senha) VALUES (?, ?)", (novo_usuario, nova_senha))
                conn.commit()
            except sqlite3.IntegrityError:
                return render_template('usuarios.html', erro='Usuário já existe!', usuarios=[], atual=session['usuario'])

        elif acao == 'alterar':
            usuario = request.form.get('alvo_usuario')
            nova_senha = hashlib.sha256(request.form.get('nova_senha').encode()).hexdigest()
            c.execute("UPDATE usuarios SET senha=? WHERE usuario=?", (nova_senha, usuario))
            conn.commit()

        elif acao == 'remover':
            usuario = request.form.get('alvo_usuario')
            if usuario != session['usuario']:
                c.execute("DELETE FROM usuarios WHERE usuario=?", (usuario,))
                conn.commit()

    c.execute("SELECT usuario FROM usuarios")
    lista_usuarios = [u[0] for u in c.fetchall()]
    conn.close()
    return render_template('usuarios.html', usuarios=lista_usuarios, atual=session['usuario'])

# Página para adicionar filmes ou séries (pesquisa TMDb)
@app.route('/add_conteudo')
@login_required
def add_conteudo():
    tmdb_key = carregar_tmdb_key()
    if not tmdb_key:
        return redirect('/dashboard')
    return render_template('pesquisa.html')

# Pesquisa TMDb (filmes ou séries)
@app.route('/pesquisar_conteudo', methods=['POST'])
@login_required
def pesquisar_conteudo():
    tmdb_key = carregar_tmdb_key()
    if not tmdb_key:
        return {"error": "API Key não configurada"}, 400

    query = request.form.get('query')
    tipo = request.form.get('tipo')  # filme ou serie
    if not query:
        return {"error": "Termo de busca vazio"}, 400
    if tipo not in ['filme', 'serie']:
        return {"error": "Tipo inválido"}, 400

    url_base = "https://api.themoviedb.org/3/search/"
    url = f"{url_base}movie" if tipo == 'filme' else f"{url_base}tv"

    params = {
        "api_key": tmdb_key,
        "language": "pt-BR",
        "query": query,
        "page": 1,
        "include_adult": False
    }
    response = requests.get(url, params=params)
    data = response.json()
    return data

# Salvar filme ou série no banco local
@app.route('/salvar_conteudo', methods=['POST'])
@login_required
def salvar_conteudo():
    tmdb_key = carregar_tmdb_key()
    if not tmdb_key:
        return {"erro": "API Key não configurada"}, 400

    titulo = request.form.get('titulo')
    ano = request.form.get('ano')
    tipo = request.form.get('tipo')
    tmdb_id = request.form.get('tmdb_id')

    if tipo not in ['filme', 'serie']:
        return {"erro": "Tipo inválido"}, 400
    if not tmdb_id:
        return {"erro": "ID TMDb ausente"}, 400

    url_base = "https://api.themoviedb.org/3"
    url = f"{url_base}/movie/{tmdb_id}" if tipo == 'filme' else f"{url_base}/tv/{tmdb_id}"

    params = {
        "api_key": tmdb_key,
        "language": "pt-BR"
    }
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        return {"erro": "Falha ao obter dados do TMDb"}, 500
    dados = resp.json()

    generos_nomes = ', '.join([g['name'] for g in dados.get('genres', [])])

    sinopse = dados.get('overview', '')
    banner = dados.get('backdrop_path') or dados.get('poster_path') or ''
    banner_url = f"/img{banner}" if banner else ''

    temporadas = dados.get('number_of_seasons', 0) if tipo == 'serie' else 0

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO conteudos (titulo, ano, genero, sinopse, banner, tipo, temporadas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        titulo,
        ano,
        generos_nomes,
        sinopse,
        banner_url,
        tipo,
        temporadas
    ))
    conn.commit()
    conn.close()

    return redirect('/dashboard')

# API para filmes
@app.route('/api/filmes', methods=['GET'])
@login_required
def api_filmes():
    page = request.args.get('page', default=1, type=int)
    limit = 50
    offset = (page - 1) * limit

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM conteudos WHERE tipo='filme'")
    total = c.fetchone()[0]

    c.execute('''
        SELECT titulo, banner, banner, genero, ano, sinopse
        FROM conteudos
        WHERE tipo = 'filme'
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

# API para séries
@app.route('/api/series', methods=['GET'])
@login_required
def api_series():
    page = request.args.get('page', default=1, type=int)
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

    series_list = []
    for s in series:
        series_list.append({
            "id": s[0],
            "nome": s[1],
            "banner": f"/img/{s[2]}",
            "genero": s[3],
            "sinopse": s[4],
            "ano": s[5],
            "temporadas": s[6] or 0
        })

    total_pages = (total + limit - 1) // limit
    next_page = page + 1 if page < total_pages else None

    return jsonify({
        "pagina_atual": page,
        "total_paginas": total_pages,
        "total_series": total,
        "series": series_list,
        "proxima_pagina": f"/api/series?page={next_page}" if next_page else None
    })

# Rota para adicionar temporadas e episódios
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

        for temporada in range(1, num_temporadas + 1):
            try:
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
            except sqlite3.OperationalError as e:
                conn.rollback()
                conn.close()
                return f"Erro ao inserir temporada {temporada}: {e}", 500

        c.execute("UPDATE conteudos SET temporadas=? WHERE id=?", (num_temporadas, serie_id))
        conn.commit()
        conn.close()
        return redirect('/dashboard')

    c.execute("SELECT id, titulo FROM conteudos WHERE tipo='serie'")
    series = c.fetchall()
    conn.close()
    return render_template('add_temporadas.html', series=series)

# API detalhada da série com temporadas e episódios
@app.route('/api/serie/<int:serie_id>', methods=['GET'])
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
        "banner": f"/img/{serie[2]}",
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
            SELECT numero, nome, sinopse, capa
            FROM episodios 
            WHERE temporada_id = ? 
            ORDER BY numero ASC
        """, (temporada_id,))
        episodios = c.fetchall()

        episodios_list = []
        for ep in episodios:
            episodios_list.append({
                "episodio_numero": ep[0],
                "nome": ep[1],
                "sinopse": ep[2],
                "capa": f"/img_eps/{ep[3]}" if ep[3] else None
            })

        serie_info["temporadas"].append({
            "temporada_numero": numero_temp,
            "episodios": episodios_list
        })

    conn.close()
    return jsonify(serie_info)

# Rota para imagens dos episódios
@app.route('/img_eps/<path:still_path>')
def imagem_episodio(still_path):
    url = f'https://image.tmdb.org/t/p/w500/{still_path}'
    response = requests.get(url)
    if response.status_code == 200:
        return send_file(BytesIO(response.content), mimetype='image/jpeg')
    return "Imagem não encontrada", 404

# Rodar com Gunicorn, não usar app.run()
# Para testar localmente sem Gunicorn, rode: FLASK_APP=app.py flask run

