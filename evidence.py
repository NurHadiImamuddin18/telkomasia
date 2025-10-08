from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error
import json
import base64
from datetime import datetime
import os
from functools import wraps
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)

load_dotenv()
# MySQL Configuration
DB_CONFIG = {
    'host': os.getenv("MYSQLHOST"),
    'database': os.getenv("MYSQLDATABASE"),
    'user': os.getenv("MYSQLUSER"),
    'password': os.getenv("MYSQLPASSWORD"),
    'port': int(os.getenv("MYSQLPORT", 3306))
}

# PERBAIKAN: Decorator untuk cek role admin yang lebih robust
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Cek dari berbagai sumber
        user_role = None
        
        # 1. Cek dari header
        user_role = request.headers.get('X-User-Role')
        
        # 2. Jika tidak ada di header, cek dari JSON body
        if not user_role and request.is_json:
            data = request.json
            user_role = data.get('userRole') or data.get('role')
        
        # 3. Jika tidak ada, cek dari form data
        if not user_role:
            user_role = request.form.get('userRole') or request.form.get('role')
        
        # Validasi role
        if user_role != 'admin':
            return jsonify({
                'success': False, 
                'message': 'Unauthorized. Admin access required.',
                'debug_info': f'Received role: {user_role}'  # Untuk debugging
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function

def get_db():
    """Connect to the MySQL database"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def init_db():
    """Initialize database with required tables"""
    conn = get_db()
    if not conn:
        print("Failed to connect to database")
        return
    
    cursor = conn.cursor()
    
    try:
        # Table for users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table for orders (DW and FAT)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id VARCHAR(255) NOT NULL,
                type VARCHAR(50) NOT NULL,
                nama_teknisi VARCHAR(255) NOT NULL,
                materials TEXT,
                foto_count INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255)
            )
        ''')
        
        # Table for photos (DW photos)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT,
                image_data LONGTEXT,
                caption TEXT,
                photo_index INT,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            )
        ''')
        
        # Table for FAT photos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fat_photos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT,
                photo_key VARCHAR(100) NOT NULL,
                image_data LONGTEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            )
        ''')
        
        # Insert default admin user if not exists
        cursor.execute('SELECT * FROM users WHERE username = %s', ('admin',))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s)
            ''', ('admin', 'admin123', 'admin'))
        
        # Insert default user if not exists
        cursor.execute('SELECT * FROM users WHERE username = %s', ('teknisi',))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s)
            ''', ('teknisi', 'teknisi123', 'user'))
        
        conn.commit()
        print("Database initialized successfully")
        print("Default users created:")
        print("  - admin / admin123 (Administrator)")
        print("  - teknisi / teknisi123 (User)")
    except Error as e:
        print(f"Error initializing database: {e}")
    finally:
        cursor.close()
        conn.close()

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('prototype_change_dw_fat_v2.1.html')

@app.route('/api/login', methods=['POST'])
def login():
    """Handle user login"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', 
                   (username, password))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user:
        return jsonify({
            'success': True,
            'user': {
                'username': user['username'],
                'role': user['role']
            }
        })
    else:
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id, username, role, created_at FROM users')
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'users': users})

@app.route('/api/users', methods=['POST'])
@admin_required
def add_user():
    """Add new user"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')
    
    # Validasi input
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO users (username, password, role) 
            VALUES (%s, %s, %s)
        ''', (username, password, role))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'User added successfully'})
    except mysql.connector.IntegrityError:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete user"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    # Check if user is admin
    cursor.execute('SELECT role FROM users WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    
    if user and user['role'] == 'admin':
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Cannot delete admin user'}), 400
    
    cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'message': 'User deleted successfully'})

@app.route('/api/orders', methods=['POST'])
@admin_required
def create_order():
    """Create new order (DW or FAT)"""
    data = request.json
    order_id = data.get('orderId')
    order_type = data.get('type')
    nama_teknisi = data.get('namaTeknisi')
    materials = json.dumps(data.get('materials', []))
    foto_count = data.get('fotoCount', 0)
    created_by = data.get('createdBy')
    
    # Validasi input
    if not order_id or not order_type or not nama_teknisi:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO orders (order_id, type, nama_teknisi, materials, foto_count, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (order_id, order_type, nama_teknisi, materials, foto_count, created_by))
        
        new_order_id = cursor.lastrowid
        
        # Save photos for DW
        if order_type == 'DW' and 'fotoData' in data:
            for idx, foto in enumerate(data['fotoData']):
                cursor.execute('''
                    INSERT INTO photos (order_id, image_data, caption, photo_index)
                    VALUES (%s, %s, %s, %s)
                ''', (new_order_id, foto['src'], foto.get('caption', ''), idx))
        
        # Save photos for FAT
        if order_type == 'FAT' and 'fatPhotos' in data:
            for key, image_data in data['fatPhotos'].items():
                cursor.execute('''
                    INSERT INTO fat_photos (order_id, photo_key, image_data)
                    VALUES (%s, %s, %s)
                ''', (new_order_id, key, image_data))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Order created successfully', 'id': new_order_id})
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Get all orders"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM orders ORDER BY created_at DESC')
    orders = cursor.fetchall()
    
    result = []
    for order in orders:
        order_dict = dict(order)
        order_dict['materials'] = json.loads(order_dict['materials'])
        
        # Convert snake_case to camelCase for frontend compatibility
        order_dict['orderId'] = order_dict['order_id']
        order_dict['namaTeknisi'] = order_dict['nama_teknisi']
        order_dict['fotoCount'] = order_dict['foto_count']
        order_dict['createdBy'] = order_dict.get('created_by')
        order_dict['createdAt'] = order_dict.get('created_at')
        
        result.append(order_dict)
    
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'orders': result})

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order_detail(order_id):
    """Get order detail"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM orders WHERE id = %s', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Order not found'}), 404
    
    order_dict = dict(order)
    order_dict['materials'] = json.loads(order_dict['materials'])
    
    # Convert field names
    order_dict['orderId'] = order_dict['order_id']
    order_dict['namaTeknisi'] = order_dict['nama_teknisi']
    order_dict['fotoCount'] = order_dict['foto_count']
    order_dict['createdBy'] = order_dict.get('created_by')
    order_dict['createdAt'] = order_dict.get('created_at')
    
    # Get photos for DW orders
    if order_dict['type'] == 'DW':
        cursor.execute('SELECT image_data, caption, photo_index FROM photos WHERE order_id = %s ORDER BY photo_index', 
                      (order_id,))
        photos = cursor.fetchall()
        order_dict['fotoData'] = [{'src': p['image_data'], 'caption': p['caption']} for p in photos]
    
    # Get photos for FAT orders
    if order_dict['type'] == 'FAT':
        cursor.execute('SELECT photo_key, image_data FROM fat_photos WHERE order_id = %s', 
                      (order_id,))
        fat_photos = cursor.fetchall()
        order_dict['fatPhotos'] = {p['photo_key']: p['image_data'] for p in fat_photos}
    
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'order': order_dict})

@app.route('/api/orders/<int:order_id>', methods=['PUT'])
@admin_required
def update_order(order_id):
    """Update order"""
    data = request.json
    materials = json.dumps(data.get('materials', []))
    foto_count = data.get('fotoCount')
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE orders 
            SET materials = %s, foto_count = %s
            WHERE id = %s
        ''', (materials, foto_count, order_id))
        
        # Update DW photos if provided
        if 'fotoData' in data:
            # Delete old photos
            cursor.execute('DELETE FROM photos WHERE order_id = %s', (order_id,))
            # Insert new photos
            for idx, foto in enumerate(data['fotoData']):
                cursor.execute('''
                    INSERT INTO photos (order_id, image_data, caption, photo_index)
                    VALUES (%s, %s, %s, %s)
                ''', (order_id, foto['src'], foto.get('caption', ''), idx))
        
        # Update FAT photos if provided
        if 'fatPhotos' in data:
            # Delete old photos
            cursor.execute('DELETE FROM fat_photos WHERE order_id = %s', (order_id,))
            # Insert new photos
            for key, image_data in data['fatPhotos'].items():
                cursor.execute('''
                    INSERT INTO fat_photos (order_id, photo_key, image_data)
                    VALUES (%s, %s, %s)
                ''', (order_id, key, image_data))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Order updated successfully'})
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/orders/<int:order_id>', methods=['DELETE'])
@admin_required
def delete_order(order_id):
    """Delete order"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM orders WHERE id = %s', (order_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Order deleted successfully'})
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    # Create templates folder if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    # Initialize database
    print("="*50)
    print("Initializing MySQL Database...")
    print("="*50)
    init_db()
    
    print("\n" + "="*50)
    print("Starting Flask Server...")
    print("="*50)
    print("Server running at: http://localhost:5000")
    print("="*50)
    
    # Run the app
    app.run(debug=True, host='0.0.0.0', port=5000)