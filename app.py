from flask import Flask, render_template, request, jsonify, session
import json
import os
import uuid
import random
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'texas_poker_secret_key'

# 游戏配置文件路径
CONFIG_FILE = 'game_config.json'
GAME_DATA_FILE = 'game_data.json'

# 默认游戏配置
DEFAULT_CONFIG = {
    'small_blind': 10,
    'big_blind': 20,
    'buy_in_amount': 1000
}

# 默认游戏数据
DEFAULT_GAME_DATA = {
    'players': {},
    'game_state': 'waiting',
    'current_pot': 0,
    'dealer_position': 0,
    'current_player': None,
    'betting_round': 'preflop',
    'community_cards': [],
    'deck': [],
    'side_pots': [],
    'min_bet': 0
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

@app.route('/')
def index():
    """主游戏页面"""
    return render_template('index.html')

@app.route('/admin')
def admin():
    """后台管理页面"""
    config = load_config()
    return render_template('admin.html', config=config)

@app.route('/api/join_game', methods=['POST'])
def join_game():
    """玩家加入游戏"""
    data = request.get_json()
    player_id = data.get('player_id', '').strip()
    
    if not player_id:
        return jsonify({'success': False, 'message': '请输入有效的玩家ID'})
    
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

@app.route('/api/get_game_state')
def get_game_state():
    """获取游戏状态"""
    game_data = load_game_data()
    config = load_config()
    player_id = session.get('player_id')
    
    # 为当前玩家提供手牌信息
    current_player_cards = None
    if player_id and player_id in game_data['players']:
        current_player_cards = game_data['players'][player_id].get('hole_cards', [])
    
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
        'my_cards': current_player_cards
    })

@app.route('/api/player_action', methods=['POST'])
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
def update_config():
    """更新游戏配置"""
    data = request.get_json()
    
    config = load_config()
    config['small_blind'] = int(data.get('small_blind', config['small_blind']))
    config['big_blind'] = int(data.get('big_blind', config['big_blind']))
    config['buy_in_amount'] = int(data.get('buy_in_amount', config['buy_in_amount']))
    
    save_config(config)
    
    return jsonify({'success': True, 'message': '配置更新成功', 'config': config})

@app.route('/api/start_game', methods=['POST'])
def start_game():
    """开始游戏"""
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
    
    # 初始化游戏
    game_data['game_state'] = 'playing'
    game_data['betting_round'] = 'preflop'
    game_data['current_pot'] = 0
    game_data['community_cards'] = []
    game_data['side_pots'] = []
    
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
    
    save_game_data(game_data)
    
    return jsonify({'success': True, 'message': '游戏开始！发牌完成，请下注。', 'game_state': 'playing'})

@app.route('/api/reset_game', methods=['POST'])
def reset_game():
    """重置游戏"""
    save_game_data(DEFAULT_GAME_DATA.copy())
    return jsonify({'success': True, 'message': '游戏已重置'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)
