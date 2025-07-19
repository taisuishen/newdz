from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import os
import uuid
import random
import time
import threading
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'texas_poker_secret_key'

# 用户认证配置
USERS_FILE = 'users.json'
ADMIN_USERS = {'admin': 'admin123'}  # 管理员账户

# 默认用户数据
DEFAULT_USERS = {
    'admin': {
        'password': 'admin123',
        'role': 'admin',
        'created_at': datetime.now().isoformat()
    },
    'player1': {
        'password': '123456',
        'role': 'player',
        'created_at': datetime.now().isoformat()
    },
    'player2': {
        'password': '123456',
        'role': 'player',
        'created_at': datetime.now().isoformat()
    }
}

# 游戏配置文件路径
CONFIG_FILE = 'game_config.json'
GAME_DATA_FILE = 'game_data.json'

# 默认游戏配置
DEFAULT_CONFIG = {
    'small_blind': 10,
    'big_blind': 20,
    'buy_in_amount': 1000,
    'action_timeout': 30,  # 玩家行动超时时间（秒）
    'ready_timeout': 60    # 准备超时时间（秒）
}

# 默认游戏数据
DEFAULT_GAME_DATA = {
    'players': {},
    'game_state': 'waiting',  # waiting, ready_phase, playing
    'current_pot': 0,
    'dealer_position': 0,
    'current_player': None,
    'betting_round': 'preflop',
    'community_cards': [],
    'deck': [],
    'side_pots': [],
    'min_bet': 0,
    'ready_players': [],  # 已准备的玩家
    'ready_start_time': None,  # 准备阶段开始时间
    'action_start_time': None,  # 当前玩家行动开始时间
    'timers': {}  # 存储各种计时器
}

# 扑克牌定义
SUITS = ['♠', '♥', '♦', '♣']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

def create_deck():
    """创建一副新牌"""
    deck = []
    for suit in SUITS:
        for rank in RANKS:
            deck.append({'suit': suit, 'rank': rank})
    random.shuffle(deck)
    return deck

def deal_hole_cards(game_data):
    """发底牌给每个玩家"""
    active_players = [p for p in game_data['players'].values() if p.get('position') is not None and p.get('chips', 0) > 0]
    
    # 每个玩家发2张牌
    for player in active_players:
        player['hole_cards'] = []
        for _ in range(2):
            if game_data['deck']:
                card = game_data['deck'].pop()
                player['hole_cards'].append(card)
        player['current_bet'] = 0
        player['folded'] = False
        player['all_in'] = False

def get_next_player_position(game_data, current_pos):
    """获取下一个玩家位置"""
    active_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None and not p.get('folded', False) and p.get('chips', 0) > 0]
    
    if not active_players:
        return None
        
    positions = sorted([p['position'] for p in active_players])
    
    try:
        current_index = positions.index(current_pos)
        next_index = (current_index + 1) % len(positions)
        return positions[next_index]
    except ValueError:
        return positions[0] if positions else None

def post_blinds(game_data, config):
    """下盲注"""
    active_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None and p.get('chips', 0) > 0]
    
    if len(active_players) < 2:
        return
    
    positions = sorted([p['position'] for p in active_players])
    dealer_pos = game_data['dealer_position']
    
    # 找到庄家位置在active_players中的索引
    try:
        dealer_index = positions.index(dealer_pos)
    except ValueError:
        dealer_index = 0
        game_data['dealer_position'] = positions[0]
    
    # 小盲位置（庄家下一位）
    small_blind_pos = positions[(dealer_index + 1) % len(positions)]
    # 大盲位置（小盲下一位）
    big_blind_pos = positions[(dealer_index + 2) % len(positions)]
    
    # 下小盲
    for player in game_data['players'].values():
        if player.get('position') == small_blind_pos:
            blind_amount = min(config['small_blind'], player['chips'])
            player['chips'] -= blind_amount
            player['current_bet'] = blind_amount
            game_data['current_pot'] += blind_amount
            if player['chips'] == 0:
                player['all_in'] = True
            break
    
    # 下大盲
    for player in game_data['players'].values():
        if player.get('position') == big_blind_pos:
            blind_amount = min(config['big_blind'], player['chips'])
            player['chips'] -= blind_amount
            player['current_bet'] = blind_amount
            game_data['current_pot'] += blind_amount
            if player['chips'] == 0:
                player['all_in'] = True
            break
    
    # 设置最小下注额和当前玩家
    game_data['min_bet'] = config['big_blind']
    # 第一个行动的玩家是大盲的下一位
    game_data['current_player'] = get_next_player_position(game_data, big_blind_pos)

def load_config():
    """加载游戏配置"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """保存游戏配置"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_game_data():
    """加载游戏数据"""
    if os.path.exists(GAME_DATA_FILE):
        with open(GAME_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_GAME_DATA.copy()

def save_game_data(data):
    """保存游戏数据"""
    with open(GAME_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_users():
    """加载用户数据"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_USERS.copy()

def save_users(users):
    """保存用户数据"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'success': False, 'message': '请先登录', 'redirect': '/login'})
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """管理员权限验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'success': False, 'message': '请先登录'})
        users = load_users()
        username = session['username']
        if username not in users or users[username].get('role') != 'admin':
            return jsonify({'success': False, 'message': '需要管理员权限'})
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    """主游戏页面"""
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login')
def login():
    """登录页面"""
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    """用户登录"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'message': '请输入用户名和密码'})
    
    users = load_users()
    
    if username not in users:
        return jsonify({'success': False, 'message': '用户名不存在'})
    
    if users[username]['password'] != password:
        return jsonify({'success': False, 'message': '密码错误'})
    
    session['username'] = username
    session['role'] = users[username].get('role', 'player')
    
    return jsonify({
        'success': True, 
        'message': '登录成功',
        'role': users[username].get('role', 'player')
    })

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """用户登出"""
    session.clear()
    return jsonify({'success': True, 'message': '已退出登录'})

@app.route('/admin')
def admin():
    """后台管理页面"""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    users = load_users()
    username = session['username']
    if username not in users or users[username].get('role') != 'admin':
        return redirect(url_for('index'))
    
    config = load_config()
    return render_template('admin.html', config=config)

@app.route('/api/join_game', methods=['POST'])
@login_required
def join_game():
    """玩家加入游戏"""
    player_id = session.get('username')
    
    if not player_id:
        return jsonify({'success': False, 'message': '用户未登录'})
    
    game_data = load_game_data()
    config = load_config()
    
    # 检查玩家是否已存在
    if player_id in game_data['players']:
        player = game_data['players'][player_id]
    else:
        # 新玩家加入
        player = {
            'id': player_id,
            'chips': config['buy_in_amount'],
            'win_loss': -config['buy_in_amount'],  # 初始输赢金额为负的买入金额
            'position': None,
            'joined_at': datetime.now().isoformat()
        }
        game_data['players'][player_id] = player
    
    save_game_data(game_data)
    session['player_id'] = player_id
    
    return jsonify({
        'success': True, 
        'player': player,
        'config': config
    })

@app.route('/api/change_position', methods=['POST'])
@login_required
def change_position():
    """切换玩家位置"""
    data = request.get_json()
    player_id = session.get('player_id')
    new_position = data.get('position')
    
    if not player_id:
        return jsonify({'success': False, 'message': '请先加入游戏'})
    
    game_data = load_game_data()
    
    if player_id not in game_data['players']:
        return jsonify({'success': False, 'message': '玩家不存在'})
    
    # 检查位置是否被占用
    for pid, player in game_data['players'].items():
        if pid != player_id and player.get('position') == new_position:
            return jsonify({'success': False, 'message': '该位置已被占用'})
    
    game_data['players'][player_id]['position'] = new_position
    save_game_data(game_data)
    
    return jsonify({'success': True, 'message': '位置切换成功'})

@app.route('/api/add_chips', methods=['POST'])
@login_required
def add_chips():
    """添加筹码"""
    data = request.get_json()
    player_id = session.get('player_id')
    amount = data.get('amount', 0)
    
    if not player_id:
        return jsonify({'success': False, 'message': '请先加入游戏'})
    
    if amount <= 0:
        return jsonify({'success': False, 'message': '添加金额必须大于0'})
    
    game_data = load_game_data()
    config = load_config()
    
    if player_id not in game_data['players']:
        return jsonify({'success': False, 'message': '玩家不存在'})
    
    player = game_data['players'][player_id]
    player['chips'] += amount
    player['win_loss'] -= amount  # 添加筹码会减少输赢金额
    
    save_game_data(game_data)
    
    return jsonify({
        'success': True, 
        'player': player,
        'message': f'成功添加 {amount} 筹码'
    })

def check_timeouts(game_data, config):
    """检查各种超时情况"""
    current_time = time.time()
    
    # 检查准备阶段超时
    if (game_data['game_state'] == 'ready_phase' and 
        game_data.get('ready_start_time') and 
        current_time - game_data['ready_start_time'] > config['ready_timeout']):
        
        # 踢出未准备的玩家
        players_to_remove = []
        ready_players = game_data.get('ready_players', set())
        if isinstance(ready_players, list):
            ready_players = set(ready_players)
            
        for player_id, player in game_data['players'].items():
            if (player.get('position') is not None and 
                player_id not in ready_players):
                players_to_remove.append(player_id)
        
        for player_id in players_to_remove:
            print(f"玩家 {player_id} 准备超时，被踢出游戏")
            game_data['players'][player_id]['position'] = None
            game_data['players'][player_id]['chips'] = 0
        
        # 从准备列表中移除被踢出的玩家
        game_data['ready_players'] = ready_players - set(players_to_remove)
        
        # 重新检查是否可以开始游戏
        remaining_players = [p for p in game_data['players'].values() if p.get('position') is not None]
        if len(remaining_players) >= 2 and len(game_data['ready_players']) == len(remaining_players):
            start_game_internal(game_data, config)
        else:
            # 重置到等待状态
            game_data['game_state'] = 'waiting'
            game_data['ready_players'] = set()
            game_data['ready_start_time'] = None
            
        save_game_data(game_data)
    
    # 检查行动超时
    elif (game_data['game_state'] == 'playing' and 
          game_data.get('action_start_time') and 
          current_time - game_data['action_start_time'] > config['action_timeout']):
        
        # 找到当前行动的玩家
        current_player_pos = game_data.get('current_player')
        current_player = None
        current_player_id = None
        
        if current_player_pos:
            for player_id, player in game_data['players'].items():
                if player.get('position') == current_player_pos:
                    current_player = player
                    current_player_id = player_id
                    break
        
        if current_player and not current_player.get('folded') and not current_player.get('all_in'):
            # 自动过牌或弃牌
            max_bet = max([p.get('current_bet', 0) for p in game_data['players'].values() if p.get('position') is not None], default=0)
            if current_player.get('current_bet', 0) == max_bet:
                # 可以过牌，不需要额外操作
                print(f"玩家 {current_player_id} 行动超时，自动过牌")
            else:
                # 需要跟注，自动弃牌
                current_player['folded'] = True
                print(f"玩家 {current_player_id} 行动超时，自动弃牌")
            
            # 移动到下一个玩家
            game_data['current_player'] = get_next_player_position(game_data, current_player_pos)
            game_data['action_start_time'] = time.time()
            
            # 检查是否需要进入下一轮或结束游戏
            check_betting_round_end(game_data)
            
            save_game_data(game_data)

@app.route('/api/get_game_state')
@login_required
def get_game_state():
    """获取游戏状态"""
    game_data = load_game_data()
    config = load_config()
    player_id = session.get('player_id')
    
    # 检查超时
    check_timeouts(game_data, config)
    
    # 为当前玩家提供手牌信息
    current_player_cards = None
    if player_id and player_id in game_data['players']:
        current_player_cards = game_data['players'][player_id].get('hole_cards', [])
    
    # 计算剩余时间
    remaining_time = None
    if game_data['game_state'] == 'ready_phase' and game_data.get('ready_start_time'):
        elapsed = time.time() - game_data['ready_start_time']
        remaining_time = max(0, config['ready_timeout'] - elapsed)
    elif game_data['game_state'] == 'playing' and game_data.get('action_start_time'):
        elapsed = time.time() - game_data['action_start_time']
        remaining_time = max(0, config['action_timeout'] - elapsed)
    
    return jsonify({
        'players': game_data['players'],
        'config': config,
        'game_state': game_data['game_state'],
        'current_pot': game_data.get('current_pot', 0),
        'community_cards': game_data.get('community_cards', []),
        'current_player': game_data.get('current_player'),
        'betting_round': game_data.get('betting_round', 'preflop'),
        'min_bet': game_data.get('min_bet', 0),
        'dealer_position': game_data.get('dealer_position', 0),
        'my_cards': current_player_cards,
        'ready_players': list(game_data.get('ready_players', set())),
        'remaining_time': remaining_time
    })

@app.route('/api/player_action', methods=['POST'])
@login_required
def player_action():
    """玩家行动"""
    data = request.get_json()
    player_id = session.get('player_id')
    action = data.get('action')  # 'call', 'raise', 'fold', 'check'
    amount = data.get('amount', 0)
    
    if not player_id:
        return jsonify({'success': False, 'message': '请先加入游戏'})
    
    game_data = load_game_data()
    config = load_config()
    
    if game_data['game_state'] != 'playing':
        return jsonify({'success': False, 'message': '游戏未开始'})
    
    if player_id not in game_data['players']:
        return jsonify({'success': False, 'message': '玩家不存在'})
    
    player = game_data['players'][player_id]
    
    # 检查是否轮到该玩家
    if game_data.get('current_player') != player.get('position'):
        return jsonify({'success': False, 'message': '还没轮到您行动'})
    
    # 检查玩家是否已弃牌或全押
    if player.get('folded') or player.get('all_in'):
        return jsonify({'success': False, 'message': '您已无法继续行动'})
    
    # 处理不同行动
    if action == 'fold':
        player['folded'] = True
        message = f'{player_id} 弃牌'
    
    elif action == 'check':
        # 只有在没有人加注时才能过牌
        max_bet = max([p.get('current_bet', 0) for p in game_data['players'].values()])
        if player.get('current_bet', 0) < max_bet:
            return jsonify({'success': False, 'message': '有人加注，您不能过牌'})
        message = f'{player_id} 过牌'
    
    elif action == 'call':
        max_bet = max([p.get('current_bet', 0) for p in game_data['players'].values()])
        call_amount = max_bet - player.get('current_bet', 0)
        
        if call_amount > player['chips']:
            # 全押
            call_amount = player['chips']
            player['all_in'] = True
        
        player['chips'] -= call_amount
        player['current_bet'] += call_amount
        game_data['current_pot'] += call_amount
        
        if player['chips'] == 0:
            player['all_in'] = True
            message = f'{player_id} 全押跟注 {call_amount}'
        else:
            message = f'{player_id} 跟注 {call_amount}'
    
    elif action == 'raise':
        max_bet = max([p.get('current_bet', 0) for p in game_data['players'].values()])
        call_amount = max_bet - player.get('current_bet', 0)
        total_bet = call_amount + amount
        
        if total_bet > player['chips']:
            return jsonify({'success': False, 'message': '筹码不足'})
        
        if amount < game_data.get('min_bet', config['big_blind']):
            return jsonify({'success': False, 'message': f'加注金额至少为 {game_data.get("min_bet", config["big_blind"])}'})
        
        player['chips'] -= total_bet
        player['current_bet'] += total_bet
        game_data['current_pot'] += total_bet
        
        if player['chips'] == 0:
            player['all_in'] = True
            message = f'{player_id} 全押加注到 {player["current_bet"]}'
        else:
            message = f'{player_id} 加注到 {player["current_bet"]}'
    
    else:
        return jsonify({'success': False, 'message': '无效的行动'})
    
    # 移动到下一个玩家
    game_data['current_player'] = get_next_player_position(game_data, player['position'])
    game_data['action_start_time'] = time.time()  # 重置行动计时
    
    # 检查是否需要进入下一轮或结束游戏
    check_betting_round_end(game_data)
    
    save_game_data(game_data)
    
    return jsonify({'success': True, 'message': message})

def check_betting_round_end(game_data):
    """检查下注轮是否结束"""
    active_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None and not p.get('folded', False)]
    
    # 如果只剩一个玩家，游戏结束
    if len(active_players) <= 1:
        end_hand(game_data)
        return
    
    # 检查所有活跃玩家是否都已行动且下注相等
    max_bet = max([p.get('current_bet', 0) for p in active_players])
    all_equal = all(p.get('current_bet', 0) == max_bet or p.get('all_in', False) for p in active_players)
    
    if all_equal:
        # 进入下一轮
        next_betting_round(game_data)

def next_betting_round(game_data):
    """进入下一个下注轮"""
    current_round = game_data.get('betting_round', 'preflop')
    
    # 重置所有玩家的当前下注
    for player in game_data['players'].values():
        player['current_bet'] = 0
    
    if current_round == 'preflop':
        # 发翻牌（3张公共牌）
        for _ in range(3):
            if game_data['deck']:
                game_data['community_cards'].append(game_data['deck'].pop())
        game_data['betting_round'] = 'flop'
    
    elif current_round == 'flop':
        # 发转牌（1张公共牌）
        if game_data['deck']:
            game_data['community_cards'].append(game_data['deck'].pop())
        game_data['betting_round'] = 'turn'
    
    elif current_round == 'turn':
        # 发河牌（1张公共牌）
        if game_data['deck']:
            game_data['community_cards'].append(game_data['deck'].pop())
        game_data['betting_round'] = 'river'
    
    elif current_round == 'river':
        # 摊牌
        end_hand(game_data)
        return
    
    # 设置下一轮的第一个行动玩家（庄家后第一个活跃玩家）
    active_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None and not p.get('folded', False) and not p.get('all_in', False)]
    
    if active_players:
        positions = sorted([p['position'] for p in active_players])
        dealer_pos = game_data['dealer_position']
        
        # 找到庄家后的第一个活跃玩家
        next_pos = None
        for pos in positions:
            if pos > dealer_pos:
                next_pos = pos
                break
        
        if next_pos is None:
            next_pos = positions[0]
        
        game_data['current_player'] = next_pos
        game_data['action_start_time'] = time.time()  # 重置行动计时
    else:
        # 所有人都全押了，直接到摊牌
        end_hand(game_data)

def end_hand(game_data):
    """结束当前手牌"""
    # 简化版本：将底池分给未弃牌的玩家
    active_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None and not p.get('folded', False)]
    
    if len(active_players) == 1:
        # 只有一个玩家，获得全部底池
        winner = active_players[0]
        winner['chips'] += game_data['current_pot']
        winner['win_loss'] += game_data['current_pot']
    else:
        # 多个玩家，平分底池（简化处理）
        pot_per_player = game_data['current_pot'] // len(active_players)
        for player in active_players:
            player['chips'] += pot_per_player
            player['win_loss'] += pot_per_player
    
    # 重置游戏状态
    game_data['game_state'] = 'waiting'
    game_data['current_pot'] = 0
    game_data['community_cards'] = []
    game_data['current_player'] = None
    game_data['betting_round'] = 'preflop'
    
    # 清理玩家状态
    for player in game_data['players'].values():
        player.pop('hole_cards', None)
        player.pop('current_bet', None)
        player.pop('folded', None)
        player.pop('all_in', None)
    
    # 移动庄家位置
    active_positions = [p['position'] for p in game_data['players'].values() 
                       if p.get('position') is not None and p.get('chips', 0) > 0]
    
    if active_positions:
        positions = sorted(active_positions)
        try:
            current_dealer_index = positions.index(game_data['dealer_position'])
            next_dealer_index = (current_dealer_index + 1) % len(positions)
            game_data['dealer_position'] = positions[next_dealer_index]
        except ValueError:
            game_data['dealer_position'] = positions[0]

@app.route('/api/update_config', methods=['POST'])
@admin_required
def update_config():
    """更新游戏配置"""
    data = request.get_json()
    
    config = load_config()
    config['small_blind'] = int(data.get('small_blind', config['small_blind']))
    config['big_blind'] = int(data.get('big_blind', config['big_blind']))
    config['buy_in_amount'] = int(data.get('buy_in_amount', config['buy_in_amount']))
    config['action_timeout'] = int(data.get('action_timeout', config['action_timeout']))
    config['ready_timeout'] = int(data.get('ready_timeout', config['ready_timeout']))
    
    save_config(config)
    
    return jsonify({'success': True, 'message': '配置更新成功', 'config': config})

@app.route('/api/player_ready', methods=['POST'])
@login_required
def player_ready():
    """玩家准备"""
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'success': False, 'message': '请先加入游戏'})
    
    game_data = load_game_data()
    config = load_config()
    
    if player_id not in game_data['players']:
        return jsonify({'success': False, 'message': '玩家不存在'})
    
    if game_data['players'][player_id].get('position') is None:
        return jsonify({'success': False, 'message': '请先选择座位'})
    
    if game_data['game_state'] not in ['waiting', 'ready_phase']:
        return jsonify({'success': False, 'message': '当前无法准备'})
    
    # 添加到准备列表
    if 'ready_players' not in game_data:
        game_data['ready_players'] = []
    
    if player_id not in game_data['ready_players']:
        game_data['ready_players'].append(player_id)
    
    # 如果是第一个准备的玩家，开始准备阶段
    if game_data['game_state'] == 'waiting' and len(game_data['ready_players']) == 1:
        game_data['game_state'] = 'ready_phase'
        game_data['ready_start_time'] = time.time()
    
    # 检查是否所有玩家都准备好了
    seated_players = [p for p in game_data['players'].values() if p.get('position') is not None]
    if len(game_data['ready_players']) >= len(seated_players) and len(seated_players) >= 2:
        # 所有人都准备好了，开始游戏
        start_game_internal(game_data, config)
    
    save_game_data(game_data)
    
    return jsonify({'success': True, 'message': '准备成功'})

@app.route('/api/player_unready', methods=['POST'])
@login_required
def player_unready():
    """取消准备"""
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'success': False, 'message': '请先加入游戏'})
    
    game_data = load_game_data()
    
    if game_data['game_state'] not in ['waiting', 'ready_phase']:
        return jsonify({'success': False, 'message': '当前无法取消准备'})
    
    # 从准备列表中移除
    if 'ready_players' not in game_data:
        game_data['ready_players'] = []
    
    if player_id in game_data['ready_players']:
        game_data['ready_players'].remove(player_id)
    
    # 如果没有人准备了，回到等待状态
    if len(game_data['ready_players']) == 0:
        game_data['game_state'] = 'waiting'
        game_data['ready_start_time'] = None
    
    save_game_data(game_data)
    
    return jsonify({'success': True, 'message': '取消准备成功'})

def start_game_internal(game_data, config):
    """内部开始游戏函数"""
    # 检查有位置的玩家数量
    active_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None and p.get('chips', 0) > 0]
    
    if len(active_players) < 2:
        return False
    
    # 初始化游戏
    game_data['game_state'] = 'playing'
    game_data['betting_round'] = 'preflop'
    game_data['current_pot'] = 0
    game_data['community_cards'] = []
    game_data['side_pots'] = []
    game_data['ready_players'] = []
    game_data['ready_start_time'] = None
    
    # 创建新牌组
    game_data['deck'] = create_deck()
    
    # 设置庄家位置（如果没有设置的话）
    if 'dealer_position' not in game_data or game_data['dealer_position'] == 0:
        positions = sorted([p['position'] for p in active_players])
        game_data['dealer_position'] = positions[0]
    
    # 发底牌
    deal_hole_cards(game_data)
    
    # 下盲注
    post_blinds(game_data, config)
    
    # 设置行动开始时间
    game_data['action_start_time'] = time.time()
    
    return True

@app.route('/api/start_game', methods=['POST'])
@admin_required
def start_game():
    """手动开始游戏（管理员功能）"""
    game_data = load_game_data()
    config = load_config()
    
    # 检查有位置的玩家数量
    active_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None and p.get('chips', 0) > 0]
    
    if len(active_players) < 2:
        return jsonify({'success': False, 'message': f'需要至少2名有座位的玩家才能开始游戏 (当前: {len(active_players)})'})
    
    # 检查游戏状态
    if game_data['game_state'] == 'playing':
        return jsonify({'success': False, 'message': '游戏已经在进行中'})
    
    if start_game_internal(game_data, config):
        save_game_data(game_data)
        return jsonify({'success': True, 'message': '游戏开始！发牌完成，请下注。', 'game_state': 'playing'})
    else:
        return jsonify({'success': False, 'message': '开始游戏失败'})

@app.route('/api/reset_game', methods=['POST'])
@admin_required
def reset_game():
    """重置游戏"""
    save_game_data(DEFAULT_GAME_DATA.copy())
    return jsonify({'success': True, 'message': '游戏已重置'})

@app.route('/api/get_users', methods=['GET'])
@admin_required
def get_users():
    """获取用户列表"""
    users = load_users()
    # 不返回密码信息
    safe_users = {}
    for username, user_data in users.items():
        safe_users[username] = {
            'role': user_data.get('role', 'player'),
            'created_at': user_data.get('created_at', '')
        }
    return jsonify({'success': True, 'users': safe_users})

@app.route('/api/add_user', methods=['POST'])
@admin_required
def add_user():
    """添加用户"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'player')
    
    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'})
    
    if role not in ['admin', 'player']:
        return jsonify({'success': False, 'message': '角色必须是admin或player'})
    
    users = load_users()
    
    if username in users:
        return jsonify({'success': False, 'message': '用户名已存在'})
    
    users[username] = {
        'password': password,
        'role': role,
        'created_at': datetime.now().isoformat()
    }
    
    save_users(users)
    return jsonify({'success': True, 'message': '用户添加成功'})

@app.route('/api/delete_user', methods=['POST'])
@admin_required
def delete_user():
    """删除用户"""
    data = request.get_json()
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'success': False, 'message': '用户名不能为空'})
    
    if username == 'admin':
        return jsonify({'success': False, 'message': '不能删除管理员账户'})
    
    users = load_users()
    
    if username not in users:
        return jsonify({'success': False, 'message': '用户不存在'})
    
    del users[username]
    save_users(users)
    
    # 同时从游戏中移除该玩家
    game_data = load_game_data()
    if username in game_data['players']:
        del game_data['players'][username]
        save_game_data(game_data)
    
    return jsonify({'success': True, 'message': '用户删除成功'})

@app.route('/api/change_password', methods=['POST'])
@admin_required
def change_password():
    """修改用户密码"""
    data = request.get_json()
    username = data.get('username', '').strip()
    new_password = data.get('new_password', '').strip()
    
    if not username or not new_password:
        return jsonify({'success': False, 'message': '用户名和新密码不能为空'})
    
    users = load_users()
    
    if username not in users:
        return jsonify({'success': False, 'message': '用户不存在'})
    
    users[username]['password'] = new_password
    save_users(users)
    
    return jsonify({'success': True, 'message': '密码修改成功'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)