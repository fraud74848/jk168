from functools import wraps
from flask import request, jsonify, g
import jwt
from datetime import datetime, timedelta
from models import User

SECRET_KEY = 'your-secret-key-change-this'

def generate_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(days=1),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def verify_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload['user_id']
    except:
        return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({'error': '未提供认证令牌'}), 401
        
        try:
            token = auth_header.split(' ')[1]
            user_id = verify_token(token)
            
            if not user_id:
                return jsonify({'error': '无效的认证令牌'}), 401
            
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': '用户不存在'}), 401
            
            g.current_user = user
            return f(*args, **kwargs)
        except:
            return jsonify({'error': '认证失败'}), 401
    
    return decorated