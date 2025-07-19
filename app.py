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
    """获取下一个玩家位置（包括所有有座位的玩家）"""
    # 获取所有有座位的玩家
    seated_players = [p for p in game_data['players'].values() 
                     if p.get('position') is not None]
    
    if not seated_players:
        return None
        
    positions = sorted([p['position'] for p in seated_players])
    
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
            'borrow_count': 1,  # 初始借码次数为1
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
    player['borrow_count'] += 1  # 添加筹码会增加借码次数
    
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
    
    # 检查showdown状态
    if game_data.get('game_state') == 'showdown':
        if time.time() - game_data.get('showdown_start_time', 0) >= 5:
            # 5秒后进入结算
            active_players = [(pid, p) for pid, p in game_data['players'].items() 
                             if p.get('position') is not None and not p.get('folded', False)]
            total_invested = {}
            for pid, player in game_data['players'].items():
                if player.get('position') is not None:
                    total_invested[pid] = player.get('current_bet', 0)
            
            results = calculate_hand_results(game_data, active_players, total_invested)
            game_data['hand_results'] = results
            game_data['game_state'] = 'hand_ended'
            game_data['hand_end_time'] = time.time()
            distribute_winnings(game_data, results)
            save_game_data(game_data)
    
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
    elif game_data['game_state'] == 'showdown' and game_data.get('showdown_start_time'):
        elapsed = time.time() - game_data['showdown_start_time']
        remaining_time = max(0, 5 - elapsed)
    
    response_data = {
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
    }
    
    # 添加结算信息
    if game_data.get('hand_results'):
        response_data['hand_results'] = game_data['hand_results']
    
    return jsonify(response_data)

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
        current_player_bet = player.get('current_bet', 0)
        
        # amount 是玩家想要加注到的总金额
        if amount <= max_bet:
            return jsonify({'success': False, 'message': f'加注金额必须大于当前最大下注 {max_bet}'})
        
        # 计算需要投入的筹码数量
        additional_bet = amount - current_player_bet
        
        if additional_bet > player['chips']:
            return jsonify({'success': False, 'message': '筹码不足'})
        
        if amount < max_bet + game_data.get('min_bet', config['big_blind']):
            return jsonify({'success': False, 'message': f'加注金额至少为 {max_bet + game_data.get("min_bet", config["big_blind"])}'})
        
        player['chips'] -= additional_bet
        player['current_bet'] = amount
        game_data['current_pot'] += additional_bet
        
        if player['chips'] == 0:
            player['all_in'] = True
            message = f'{player_id} 全押加注到 {amount}'
        else:
            message = f'{player_id} 加注到 {amount}'
    
    elif action == 'allin':
        # All In - 投入所有筹码
        all_in_amount = player['chips']
        if all_in_amount <= 0:
            return jsonify({'success': False, 'message': '没有筹码可以全押'})
        
        player['chips'] = 0
        player['current_bet'] += all_in_amount
        player['all_in'] = True
        game_data['current_pot'] += all_in_amount
        
        message = f'{player_id} 全押 {all_in_amount}'
    
    else:
        return jsonify({'success': False, 'message': '无效的行动'})
    
    # 移动到下一个可以行动的玩家（跳过全押和弃牌玩家）
    next_player_pos = get_next_player_position(game_data, player['position'])
    
    # 找到下一个可以行动的玩家
    attempts = 0
    max_attempts = 8  # 最多尝试8次（座位数）
    while next_player_pos and attempts < max_attempts:
        next_player = None
        for p in game_data['players'].values():
            if p.get('position') == next_player_pos:
                next_player = p
                break
        
        # 如果找到的玩家可以行动（未弃牌、未全押、有筹码），则停止
        if (next_player and not next_player.get('folded', False) and 
            not next_player.get('all_in', False) and next_player.get('chips', 0) > 0):
            break
        
        # 否则继续找下一个玩家
        next_player_pos = get_next_player_position(game_data, next_player_pos)
        attempts += 1
    
    game_data['current_player'] = next_player_pos
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
    
    # 获取可以继续行动的玩家（未弃牌、未全押、有筹码）
    can_act_players = [p for p in active_players if not p.get('all_in', False) and p.get('chips', 0) > 0]
    
    # 如果没有玩家可以继续行动，直接进入下一轮
    if len(can_act_players) == 0:
        next_betting_round(game_data)
        return
    
    # 如果只有一个玩家可以行动，直接进入下一轮
    if len(can_act_players) == 1:
        next_betting_round(game_data)
        return
    
    # 检查所有活跃玩家的下注是否相等
    max_bet = max([p.get('current_bet', 0) for p in active_players])
    all_equal = all(p.get('current_bet', 0) == max_bet or p.get('all_in', False) for p in active_players)
    
    if not all_equal:
        return  # 下注不相等，继续当前轮
    
    # 所有下注相等的情况下，需要确保每个可行动的玩家都有机会行动
    # 使用一个更简单的策略：记录每轮开始时的第一个行动玩家
    # 当行动权回到这个玩家且所有下注相等时，结束这轮
    
    # 如果没有记录第一个行动玩家，记录当前玩家
    if 'first_to_act' not in game_data:
        game_data['first_to_act'] = game_data.get('current_player')
    
    current_player_pos = game_data.get('current_player')
    first_to_act_pos = game_data.get('first_to_act')
    
    # 如果行动权回到了第一个行动的玩家，且所有下注相等，结束这轮
    if current_player_pos == first_to_act_pos and all_equal:
        # 清除第一个行动玩家的记录
        game_data.pop('first_to_act', None)
        next_betting_round(game_data)

def next_betting_round(game_data):
    """进入下一个下注轮"""
    current_round = game_data.get('betting_round', 'preflop')
    
    # 重置所有玩家的当前下注
    for player in game_data['players'].values():
        player['current_bet'] = 0
    
    # 清除第一个行动玩家的记录，为新一轮做准备
    game_data.pop('first_to_act', None)
    
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

def card_rank_value(rank):
    """获取牌面值的数值"""
    if rank == 'A':
        return 14
    elif rank == 'K':
        return 13
    elif rank == 'Q':
        return 12
    elif rank == 'J':
        return 11
    else:
        return int(rank)

def evaluate_hand(hole_cards, community_cards):
    """评估手牌强度"""
    all_cards = hole_cards + community_cards
    
    # 按花色分组
    suits = {}
    for card in all_cards:
        suit = card['suit']
        if suit not in suits:
            suits[suit] = []
        suits[suit].append(card_rank_value(card['rank']))
    
    # 按点数分组
    ranks = {}
    for card in all_cards:
        rank = card_rank_value(card['rank'])
        if rank not in ranks:
            ranks[rank] = 0
        ranks[rank] += 1
    
    # 检查同花
    flush_suit = None
    for suit, cards in suits.items():
        if len(cards) >= 5:
            flush_suit = suit
            break
    
    # 检查顺子
    sorted_ranks = sorted(ranks.keys(), reverse=True)
    straight_high = None
    
    # 检查A-2-3-4-5的特殊顺子
    if set([14, 2, 3, 4, 5]).issubset(set(sorted_ranks)):
        straight_high = 5
    else:
        # 检查普通顺子
        consecutive = 1
        for i in range(1, len(sorted_ranks)):
            if sorted_ranks[i-1] - sorted_ranks[i] == 1:
                consecutive += 1
                if consecutive >= 5:
                    straight_high = sorted_ranks[i-4]
                    break
            else:
                consecutive = 1
    
    # 检查同花顺
    if flush_suit and straight_high:
        flush_cards = sorted([card_rank_value(card['rank']) for card in all_cards if card['suit'] == flush_suit], reverse=True)
        # 检查是否有同花顺
        consecutive = 1
        straight_flush_high = None
        for i in range(1, len(flush_cards)):
            if flush_cards[i-1] - flush_cards[i] == 1:
                consecutive += 1
                if consecutive >= 5:
                    straight_flush_high = flush_cards[i-4]
                    break
            else:
                consecutive = 1
        
        # 检查A-2-3-4-5同花顺
        if set([14, 2, 3, 4, 5]).issubset(set(flush_cards)):
            straight_flush_high = 5
        
        if straight_flush_high:
            if straight_flush_high == 14:
                return (9, [14])  # 皇家同花顺
            else:
                return (8, [straight_flush_high])  # 同花顺
    
    # 检查四条
    four_kind = None
    three_kind = None
    pairs = []
    
    for rank, count in ranks.items():
        if count == 4:
            four_kind = rank
        elif count == 3:
            three_kind = rank
        elif count == 2:
            pairs.append(rank)
    
    if four_kind:
        kicker = max([r for r in ranks.keys() if r != four_kind])
        return (7, [four_kind, kicker])  # 四条
    
    # 检查葫芦
    if three_kind and pairs:
        return (6, [three_kind, max(pairs)])  # 葫芦
    
    # 检查同花
    if flush_suit:
        flush_cards = sorted([card_rank_value(card['rank']) for card in all_cards if card['suit'] == flush_suit], reverse=True)[:5]
        return (5, flush_cards)  # 同花
    
    # 检查顺子
    if straight_high:
        return (4, [straight_high])  # 顺子
    
    # 检查三条
    if three_kind:
        kickers = sorted([r for r in ranks.keys() if r != three_kind], reverse=True)[:2]
        return (3, [three_kind] + kickers)  # 三条
    
    # 检查两对
    if len(pairs) >= 2:
        pairs.sort(reverse=True)
        kicker = max([r for r in ranks.keys() if r not in pairs[:2]])
        return (2, pairs[:2] + [kicker])  # 两对
    
    # 检查一对
    if pairs:
        pair = pairs[0]
        kickers = sorted([r for r in ranks.keys() if r != pair], reverse=True)[:3]
        return (1, [pair] + kickers)  # 一对
    
    # 高牌
    high_cards = sorted(ranks.keys(), reverse=True)[:5]
    return (0, high_cards)  # 高牌

def compare_hands(hand1, hand2):
    """比较两手牌的大小，返回1表示hand1赢，-1表示hand2赢，0表示平局"""
    rank1, values1 = hand1
    rank2, values2 = hand2
    
    if rank1 > rank2:
        return 1
    elif rank1 < rank2:
        return -1
    else:
        # 同样的牌型，比较具体数值
        for v1, v2 in zip(values1, values2):
            if v1 > v2:
                return 1
            elif v1 < v2:
                return -1
        return 0

def calculate_side_pots(game_data):
    """计算边池"""
    active_players = [(pid, p) for pid, p in game_data['players'].items() 
                     if p.get('position') is not None and not p.get('folded', False)]
    
    if len(active_players) <= 1:
        return []
    
    # 按投入金额排序
    players_by_investment = []
    for pid, player in active_players:
        investment = player.get('current_bet', 0)
        players_by_investment.append((investment, pid, player))
    
    players_by_investment.sort()
    
    side_pots = []
    prev_investment = 0
    
    for i, (investment, _, _) in enumerate(players_by_investment):
        if investment > prev_investment:
            pot_amount = (investment - prev_investment) * (len(active_players) - i)
            eligible_players = [pid for _, pid, _ in players_by_investment[i:]]
            side_pots.append({
                'amount': pot_amount,
                'eligible_players': eligible_players
            })
            prev_investment = investment
    
    return side_pots

def end_hand(game_data):
    """结束当前手牌"""
    # 获取未弃牌的玩家
    active_players = [(pid, p) for pid, p in game_data['players'].items() 
                     if p.get('position') is not None and not p.get('folded', False)]
    
    # 记录每个玩家在这手牌中的投入
    total_invested = {}
    for player_id, player in game_data['players'].items():
        if player.get('position') is not None:
            total_invested[player_id] = player.get('current_bet', 0)
    
    # 检查是否有多个玩家all in
    all_in_count = sum(1 for _, p in active_players if p.get('all_in', False))
    
    # 设置游戏状态为展示阶段
    if all_in_count >= 2 and game_data.get('betting_round') != 'river':
        # 发完所有公共牌
        while len(game_data.get('community_cards', [])) < 5 and game_data['deck']:
            game_data['community_cards'].append(game_data['deck'].pop())
        
        game_data['game_state'] = 'showdown'
        game_data['showdown_start_time'] = time.time()
        save_game_data(game_data)
        return
    
    # 计算结果
    results = calculate_hand_results(game_data, active_players, total_invested)
    
    # 设置结算信息
    game_data['hand_results'] = results
    game_data['game_state'] = 'hand_ended'
    game_data['hand_end_time'] = time.time()
    
    # 分配奖金
    distribute_winnings(game_data, results)
    
    save_game_data(game_data)

def calculate_hand_results(game_data, active_players, total_invested):
    """计算手牌结果"""
    if len(active_players) == 1:
        # 只有一个玩家，获得全部底池
        winner_id, winner = active_players[0]
        pot_won = game_data['current_pot']
        net_gain = pot_won - total_invested.get(winner_id, 0)
        
        return {
            'type': 'single_winner',
            'winners': [{
                'player_id': winner_id,
                'pot_won': pot_won,
                'net_gain': net_gain,
                'hand_strength': None
            }]
        }
    
    # 多个玩家，需要比较牌力
    community_cards = game_data.get('community_cards', [])
    
    # 计算边池
    side_pots = calculate_side_pots(game_data)
    
    # 评估每个玩家的手牌
    player_hands = {}
    for pid, player in active_players:
        hole_cards = player.get('hole_cards', [])
        if hole_cards:
            hand_strength = evaluate_hand(hole_cards, community_cards)
            player_hands[pid] = {
                'strength': hand_strength,
                'hole_cards': hole_cards,
                'player': player
            }
    
    # 分配边池
    winners = []
    total_distributed = 0
    
    if side_pots:
        for pot in side_pots:
            eligible = [(pid, data) for pid, data in player_hands.items() 
                       if pid in pot['eligible_players']]
            
            if eligible:
                # 找出这个边池的赢家
                best_hand = max(eligible, key=lambda x: x[1]['strength'])
                pot_winners = [pid for pid, data in eligible 
                             if compare_hands(data['strength'], best_hand[1]['strength']) == 0]
                
                pot_per_winner = pot['amount'] // len(pot_winners)
                for winner_id in pot_winners:
                    winners.append({
                        'player_id': winner_id,
                        'pot_won': pot_per_winner,
                        'net_gain': pot_per_winner - total_invested.get(winner_id, 0),
                        'hand_strength': player_hands[winner_id]['strength']
                    })
                    total_distributed += pot_per_winner
    else:
        # 没有边池，直接比较所有玩家
        if player_hands:
            best_hand = max(player_hands.values(), key=lambda x: x['strength'])
            pot_winners = [pid for pid, data in player_hands.items() 
                         if compare_hands(data['strength'], best_hand['strength']) == 0]
            
            pot_per_winner = game_data['current_pot'] // len(pot_winners)
            for winner_id in pot_winners:
                net_gain = pot_per_winner - total_invested.get(winner_id, 0)
                winners.append({
                    'player_id': winner_id,
                    'pot_won': pot_per_winner,
                    'net_gain': net_gain,
                    'hand_strength': player_hands[winner_id]['strength']
                })
    
    return {
        'type': 'showdown',
        'winners': winners,
        'all_hands': {pid: data['strength'] for pid, data in player_hands.items()}
    }

def distribute_winnings(game_data, results):
    """分配奖金"""
    for winner in results['winners']:
        player_id = winner['player_id']
        if player_id in game_data['players']:
            game_data['players'][player_id]['chips'] += winner['pot_won']
    
    # 重置游戏状态
    game_data['current_pot'] = 0
    game_data['community_cards'] = []
    game_data['current_player'] = None
    game_data['betting_round'] = 'preflop'
    
    # 清理玩家状态
    for player in game_data['players'].values():
        player.pop('hole_cards', None)
        player['current_bet'] = 0
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

@app.route('/api/confirm_hand_result', methods=['POST'])
@login_required
def confirm_hand_result():
    """确认手牌结果"""
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'success': False, 'message': '请先加入游戏'})
    
    game_data = load_game_data()
    
    if game_data.get('game_state') != 'hand_ended':
        return jsonify({'success': False, 'message': '当前没有结算结果'})
    
    # 添加到已确认列表
    if 'confirmed_players' not in game_data:
        game_data['confirmed_players'] = []
    
    if player_id not in game_data['confirmed_players']:
        game_data['confirmed_players'].append(player_id)
    
    # 检查是否所有玩家都确认了
    active_players = [pid for pid, p in game_data['players'].items() 
                     if p.get('position') is not None]
    
    if len(game_data['confirmed_players']) >= len(active_players):
        # 所有人都确认了，回到等待状态
        game_data['game_state'] = 'waiting'
        game_data.pop('hand_results', None)
        game_data.pop('confirmed_players', None)
        game_data.pop('hand_end_time', None)
        
        # 重置玩家状态，准备下一局
        reset_players_for_next_hand(game_data)
    
    save_game_data(game_data)
    
    return jsonify({'success': True, 'message': '确认成功'})

def reset_players_for_next_hand(game_data):
    """重置玩家状态，准备下一局"""
    # 重置底池和公共牌
    game_data['current_pot'] = 0
    game_data['community_cards'] = []
    game_data['side_pots'] = []
    game_data['betting_round'] = 'preflop'
    game_data['min_bet'] = 0
    
    # 清除时间相关的状态
    game_data.pop('action_start_time', None)
    game_data.pop('showdown_start_time', None)
    game_data.pop('first_to_act', None)
    
    # 重置准备状态
    game_data['ready_players'] = []
    game_data.pop('ready_start_time', None)
    
    # 重置所有玩家的手牌状态
    for player_id, player in game_data['players'].items():
        if player.get('position') is not None:
            # 清除手牌相关状态
            player.pop('hole_cards', None)
            player.pop('current_bet', None)
            player.pop('folded', None)
            player.pop('all_in', None)
            player.pop('ready', None)  # 清除准备状态
            
            # 移除筹码为0的玩家的座位
            if player.get('chips', 0) <= 0:
                player['position'] = None
                player['chips'] = 0
    
    # 移动庄家位置到下一个有效玩家
    active_positions = sorted([p['position'] for p in game_data['players'].values() 
                              if p.get('position') is not None and p.get('chips', 0) > 0])
    
    if active_positions:
        current_dealer = game_data.get('dealer_position', 0)
        # 找到下一个有效位置
        next_dealer = None
        for pos in active_positions:
            if pos > current_dealer:
                next_dealer = pos
                break
        
        # 如果没找到，使用第一个位置
        if next_dealer is None:
            next_dealer = active_positions[0]
            
        game_data['dealer_position'] = next_dealer

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
    game_data['first_to_act'] = None  # 清除first_to_act标记
    
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