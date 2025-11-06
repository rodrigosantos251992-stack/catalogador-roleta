# app.py - Servidor Flask (Python 3) - Código Final

import datetime
import pytz
import requests
import json
import time
from collections import defaultdict, Counter
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS 
import sys
import os
from typing import Optional, Dict, List

# ====================================================
# CONFIGURAÇÃO GERAL
# ====================================================

app = Flask(__name__)
# Permite acesso cross-origin para o frontend (seu site/blog)
CORS(app) 

# URLs e Configurações 
URL_PRIMARY: str = "https://blaze.bet.br/api/singleplayer-originals/originals/roulette_games/recent/history/1"
HEADERS: dict[str, str] = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/555.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/555.36',
    'Accept': 'application/json, text/plain, * / *',
    'Connection': 'keep-alive'
}
# Define o fuso horário de Brasília (necessário para o dígito do minuto)
BRASILIA_TZ = pytz.timezone('America/Sao_Paulo')
NUM_RESULTADOS_BUSCA = 200 
# Estrutura de cache simples para controlar a frequência de acesso à API da Blaze
CACHE: Dict[str, Dict] = {'history': {'timestamp': 0, 'data': {}}} 
CACHE_LIFETIME_SECONDS = 15 

# ====================================================
# FUNÇÕES DE UTILIDADE E PROCESSAMENTO
# ====================================================

def get_brasilia_datetime(timestamp_utc_str: str) -> Optional[datetime.datetime]:
    """Converte timestamp UTC para datetime em Brasília."""
    try:
        if timestamp_utc_str.endswith('Z'):
             timestamp_utc_str = timestamp_utc_str.replace('Z', '+00:00')

        if '.' in timestamp_utc_str:
            dt_str_no_ms = timestamp_utc_str.split('.')[0]
            dt_utc_naive = datetime.datetime.strptime(dt_str_no_ms, '%Y-%m-%dT%H:%M:%S')
            dt_utc = dt_utc_naive.replace(tzinfo=datetime.timezone.utc)
        else:
            dt_utc = datetime.datetime.fromisoformat(timestamp_utc_str)

        return dt_utc.astimezone(BRASILIA_TZ)
        
    except (ValueError, TypeError, AttributeError):
        return None

def get_roll_color_char(roll_number: Optional[int]) -> str:
    """Retorna a cor em caractere: B (Branco), R (Vermelho), P (Preto)."""
    if roll_number == 0:
        return 'B'
    elif 1 <= roll_number <= 7:
        return 'R'
    elif 8 <= roll_number <= 14:
        return 'P'
    return '?'

def catalogar_padroes(resultados_list: List[Dict]) -> Dict:
    """Cataloga sequências R3+, P3+, 2x1, etc., nas últimas 90 rodadas."""
    contagem_padroes = defaultdict(int)
    
    # Pega as últimas 90 rodadas para análise de padrões
    cores = [get_roll_color_char(item.get('roll')) for item in resultados_list[:90]]
    cores_filtradas = [c for c in cores if c in ('R', 'P')] # Filtra brancos
    
    if len(cores_filtradas) < 4:
        return {}

    for i in range(len(cores_filtradas) - 3):
        seq4 = "".join(cores_filtradas[i:i+4])
        
        # Padrões de Sequência (3 ou 4 seguidos)
        if seq4.startswith('RRR'): contagem_padroes['R3+'] += 1
        if seq4.startswith('PPP'): contagem_padroes['P3+'] += 1
        if seq4 == 'RRRR': contagem_padroes['R4+'] += 1
        if seq4 == 'PPPP': contagem_padroes['P4+'] += 1

        # Padrões de Tira (Alternância)
        if seq4 == 'RPRP': contagem_padroes['Tira (4) R'] += 1
        if seq4 == 'PRPR': contagem_padroes['Tira (4) P'] += 1
        
        # Padrões 2x1
        if seq4.startswith('RRP'): contagem_padroes['2x1 R'] += 1 
        if seq4.startswith('PPR'): contagem_padroes['2x1 P'] += 1 

    return dict(contagem_padroes)

def formatar_ranking_por_digito(resultados_list: List[Dict]) -> Dict[str, int]:
    """Calcula a contagem de brancos por dígito final do minuto (0 a 9)."""
    ranking_por_digito = defaultdict(int)
    
    for item in resultados_list:
        roll_number = item.get('roll')
        created_at = item.get('created_at')
        
        if roll_number == 0 and created_at:
            dt_brasilia = get_brasilia_datetime(created_at)
            if dt_brasilia:
                # A chave do dígito é salva como STRING para o JSON
                digito_final_str = str(dt_brasilia.minute % 10) 
                ranking_por_digito[digito_final_str] += 1
                
    return dict(ranking_por_digito)


def fetch_and_process_blaze_data() -> Dict:
    """Busca, processa e formata todos os dados (Grade, Padrões, Ranking) da API."""
    
    agrupamento_por_minuto: defaultdict = defaultdict(list)
    results_list: List[Dict] = []
    
    try:
        response = requests.get(URL_PRIMARY, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        resultados_brutos = data.get('records', []) if isinstance(data, dict) and 'records' in data else data

        results_list = resultados_brutos[:NUM_RESULTADOS_BUSCA]

        for item in results_list:
            created_at = item.get('created_at')
            roll_number = item.get('roll')

            if created_at and roll_number is not None:
                dt_brasilia_item = get_brasilia_datetime(created_at)
                if dt_brasilia_item:
                    # Chave da grade como STRING para o JSON
                    digito_str = str(dt_brasilia_item.minute % 10) 
                    color_char = get_roll_color_char(roll_number)
                    
                    # Formato compacto: "NúmeroCor" (Ex: "10P", "5R", "0B")
                    formatted_roll = f"{roll_number}{color_char}"
                    
                    agrupamento_por_minuto[digito_str].append(formatted_roll)
        
        # 1. Dados da Grade
        grade_map = dict(agrupamento_por_minuto) 

        # 2. Catalogação de Padrões 
        padroes = catalogar_padroes(results_list)

        # 3. Ranking de Brancos 
        ranking = formatar_ranking_por_digito(results_list)
        
        return {
            'grade_map': grade_map,
            'padroes': padroes,
            'ranking_brancos_digito': ranking
        }

    except requests.exceptions.RequestException as e:
        print(f"[ERRO API] Falha ao buscar dados da Blaze: {e}", file=sys.stderr)
        return {'grade_map': {}, 'padroes': {}, 'ranking_brancos_digito': {}}
    except Exception as e:
        print(f"[ERRO GERAL] Falha no processamento: {e}", file=sys.stderr)
        return {'grade_map': {}, 'padroes': {}, 'ranking_brancos_digito': {}}


# ====================================================
# ENDPOINTS (ROTAS)
# ====================================================

@app.route('/api/grade-dados', methods=['GET'])
def get_grade_data():
    """Endpoint principal para retornar todos os dados processados."""
    
    current_time = time.time()
    last_update = CACHE['history']['timestamp']
    
    # Verifica o cache para não sobrecarregar a API da Blaze
    if (current_time - last_update) > CACHE_LIFETIME_SECONDS:
        print("LOG: Cache expirou. Buscando novos dados da Blaze...")
        new_data = fetch_and_process_blaze_data()
        
        CACHE['history']['data'] = new_data
        CACHE['history']['timestamp'] = current_time
    else:
        print("LOG: Retornando dados do cache.")

    dt_agora = datetime.datetime.now(BRASILIA_TZ)
    
    response_data = {
        'timestamp_br': dt_agora.strftime('%H:%M:%S'),
        # O digito_minuto_atual é um INT para facilitar a lógica do Campo Livre no JS
        'digito_minuto_atual': dt_agora.minute % 10,
        'data': CACHE['history']['data']
    }
    
    return jsonify(response_data)

@app.route('/', methods=['GET'])
def serve_index():
    """Rota para servir o arquivo index.html no acesso principal."""
    try:
        # Usa send_from_directory para servir o arquivo HTML
        return send_from_directory(os.getcwd(), 'index.html')
    except FileNotFoundError:
        return "Erro: O arquivo 'index.html' não foi encontrado. Certifique-se de que está na mesma pasta que app.py.", 404

# ====================================================
# INÍCIO DO SERVIDOR
# ====================================================

if __name__ == '__main__':
    # Verifica a presença do arquivo HTML antes de iniciar
    if not os.path.exists('index.html'):
        print("ERRO: O arquivo 'index.html' não foi encontrado na pasta. Por favor, crie e salve o código HTML na mesma pasta.")
        sys.exit(1)
        
    print("Iniciando Servidor Flask (Python 3) - Otimizado...")
    print(f"Frontend URL: http://127.0.0.1:5000/")
    
    # Inicia o servidor. Use host='0.0.0.0' para acessar de outros dispositivos na rede.
    app.run(debug=True, host='0.0.0.0', port=5000)
