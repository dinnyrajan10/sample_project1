from flask import Flask, render_template, request, jsonify, session, redirect
from werkzeug.utils import secure_filename
import os
import sqlite3
import json
from services.admin_service import build_admin_dashboard
from services.virtual_tryon_service import describe_tryon_plan, save_customer_reference
from services.gemini_service import get_gemini_styling_feedback, compose_outfit_image, generate_styling_feedback, chat_outfit_advisor

app = Flask(__name__)

# ───── CONFIG ─────
app.secret_key = "nepalthrift_secret_2026"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ───── DB CONNECTION & INIT ─────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "products.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        category TEXT NOT NULL,
        image TEXT NOT NULL,
        status TEXT DEFAULT 'Available',
        description TEXT
    )
    """)
    
    # Check if columns exist
    cursor.execute("PRAGMA table_info(products)")
    columns = [row[1] for row in cursor.fetchall()]
    if "size" not in columns:
        cursor.execute("ALTER TABLE products ADD COLUMN size TEXT DEFAULT 'M'")
    if "buying_price" not in columns:
        cursor.execute("ALTER TABLE products ADD COLUMN buying_price INTEGER DEFAULT 0")
        
    # Visitors table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS visitors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        action TEXT DEFAULT 'Visited',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone TEXT,
        location TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Cart items table (for permanent cart)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cart_items(
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, product_id)
    )
    """)
    
    # Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        customer_name TEXT,
        phone TEXT,
        location TEXT,
        total_price INTEGER,
        payment_method TEXT,
        items_json TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Check if action column exists in visitors
    cursor.execute("PRAGMA table_info(visitors)")
    v_columns = [row[1] for row in cursor.fetchall()]
    if "action" not in v_columns:
        cursor.execute("ALTER TABLE visitors ADD COLUMN action TEXT DEFAULT 'Visited'")
        
    conn.commit()
    conn.close()

init_db()


# ───── HOME / WELCOME PAGE ─────
@app.route("/")
def welcome():
    return render_template("landing.html")


# ───── SHOP PAGE ─────
@app.route("/shop")
def shop():
    username = request.args.get("username")
    if username:
        # If not explicitly logged in, they are a guest but we store their name
        if "user_id" not in session:
            session["username"] = username
            conn = get_db_connection()
            conn.execute("INSERT INTO visitors (name, action) VALUES (?, 'Guest Entry')", (username,))
            conn.commit()
            conn.close()
        
    username = session.get("username", "Guest")

    conn = get_db_connection()

    products = conn.execute("""
        SELECT * FROM products ORDER BY id DESC
    """).fetchall()

    latest_product = conn.execute("""
        SELECT * FROM products ORDER BY id DESC LIMIT 1
    """).fetchone()

    conn.close()

    return render_template(
        "index.html",
        products=products,
        latest_product=latest_product,
        username=username
    )


@app.route("/checkout")
def checkout_page():
    if not session.get("user_id"):
        return redirect("/shop")

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()

    return render_template("checkout.html", username=session.get("username", "Customer"), user=user)


# ───── ADMIN AUTHENTICATION ─────
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == "admin" and password == "admin123":
            session["is_admin"] = True
            return redirect("/admin")
        else:
            return render_template("admin_login.html", error="Invalid admin credentials.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")


# ───── ADMIN DASHBOARD ─────
@app.route("/admin")
def admin():
    if not session.get("is_admin"):
        return redirect("/admin/login")
        
    conn = get_db_connection()
    dashboard = build_admin_dashboard(conn)
    conn.close()
    
    return render_template("admin.html", **dashboard)


# ───── UPLOAD & CRUD ROUTES ─────
@app.route("/upload")
def upload_page():
    if not session.get("is_admin"):
        return redirect("/admin/login")
    return render_template("upload.html")


@app.route("/upload-product", methods=["POST"])
def upload_product():
    if not session.get("is_admin"):
        return redirect("/admin/login")
        
    name = request.form.get("name")
    price = request.form.get("price")
    buying_price = request.form.get("buying_price", 0)
    category = request.form.get("category", "Tshirt")
    size = request.form.get("size", "M")
    status = request.form.get("status", "Available")
    description = request.form.get("description", "")
    
    image = request.files.get("image")
    if image and image.filename != "":
        filename = secure_filename(image.filename)
        image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    else:
        filename = "default.jpg"
        
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO products (name, price, buying_price, category, size, status, description, image)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, int(price), int(buying_price or 0), category, size, status, description, filename))
    conn.commit()
    conn.close()
    
    return redirect("/admin")


@app.route("/edit-product/<int:id>")
def edit_product(id):
    if not session.get("is_admin"):
        return redirect("/admin/login")
    conn = get_db_connection()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (id,)).fetchone()
    conn.close()
    if not product:
        return "Product not found", 404
    return render_template("edit.html", product=product)


@app.route("/update-product/<int:id>", methods=["POST"])
def update_product(id):
    if not session.get("is_admin"):
        return redirect("/admin/login")
        
    name = request.form.get("name")
    price = request.form.get("price")
    buying_price = request.form.get("buying_price", 0)
    category = request.form.get("category")
    size = request.form.get("size")
    status = request.form.get("status")
    description = request.form.get("description")
    
    image = request.files.get("image")
    conn = get_db_connection()
    
    if image and image.filename != "":
        filename = secure_filename(image.filename)
        image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        conn.execute("""
            UPDATE products 
            SET name=?, price=?, buying_price=?, category=?, size=?, status=?, description=?, image=?
            WHERE id=?
        """, (name, int(price), int(buying_price or 0), category, size, status, description, filename, id))
    else:
        conn.execute("""
            UPDATE products 
            SET name=?, price=?, buying_price=?, category=?, size=?, status=?, description=?
            WHERE id=?
        """, (name, int(price), int(buying_price or 0), category, size, status, description, id))
        
    conn.commit()
    conn.close()
    return redirect("/admin")


@app.route("/delete-product/<int:id>")
def delete_product(id):
    if not session.get("is_admin"):
        return redirect("/admin/login")
    conn = get_db_connection()
    conn.execute("DELETE FROM products WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect("/admin")


# ───── CUSTOMER AUTHENTICATION APIS ─────
@app.route("/api/auth/signup", methods=["POST"])
def auth_signup():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"success": False, "error": "Username and password required"}), 400
    
    username = data["username"].strip()
    password = data["password"]
    phone = data.get("phone", "").strip()
    location = data.get("location", "").strip()
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, password, phone, location)
            VALUES (?, ?, ?, ?)
        """, (username, password, phone, location))
        user_id = cursor.lastrowid
        conn.commit()
        
        # Merge guest session cart into database cart
        session_cart = session.get("cart", [])
        for item in session_cart:
            cursor.execute("""
                INSERT OR IGNORE INTO cart_items (user_id, product_id)
                VALUES (?, ?)
            """, (user_id, item["id"]))
        conn.commit()
        
        # Reset session cart
        session["cart"] = []
        
        session["user_id"] = user_id
        session["username"] = username
        
        # Log event
        cursor.execute("INSERT INTO visitors (name, action) VALUES (?, 'Registered & Logged In')", (username,))
        conn.commit()
        
        return jsonify({"success": True, "username": username, "user_id": user_id})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Username already exists"}), 400
    finally:
        conn.close()


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"success": False, "error": "Username and password required"}), 400
    
    username = data["username"].strip()
    password = data["password"]
    
    conn = get_db_connection()
    user = conn.execute("""
        SELECT * FROM users WHERE username = ? AND password = ?
    """, (username, password)).fetchone()
    
    if user:
        user_id = user["id"]
        cursor = conn.cursor()
        
        # Merge session cart into database
        session_cart = session.get("cart", [])
        for item in session_cart:
            cursor.execute("""
                INSERT OR IGNORE INTO cart_items (user_id, product_id)
                VALUES (?, ?)
            """, (user_id, item["id"]))
        conn.commit()
        
        session["cart"] = []
        session["user_id"] = user_id
        session["username"] = username
        
        cursor.execute("INSERT INTO visitors (name, action) VALUES (?, 'User Logged In')", (username,))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True, 
            "username": username, 
            "user_id": user_id,
            "phone": user["phone"],
            "location": user["location"]
        })
    else:
        conn.close()
        return jsonify({"success": False, "error": "Invalid username or password"}), 401


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.pop("user_id", None)
    session.pop("username", None)
    session["cart"] = []
    return jsonify({"success": True})


@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    if session.get("user_id"):
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        conn.close()
        if user:
            return jsonify({
                "logged_in": True,
                "username": user["username"],
                "user_id": user["id"],
                "phone": user["phone"],
                "location": user["location"]
            })
    return jsonify({"logged_in": False})


# ───── CART (PERSISTENT & SESSION) ─────
def get_user_cart(user_id):
    conn = get_db_connection()
    items = conn.execute("""
        SELECT p.* FROM products p
        JOIN cart_items c ON p.id = c.product_id
        WHERE c.user_id = ?
    """, (user_id,)).fetchall()
    conn.close()
    return [dict(item) for item in items]


@app.route("/api/cart")
def get_cart():
    if session.get("user_id"):
        return jsonify(get_user_cart(session["user_id"]))
    return jsonify(session.get("cart", []))


@app.route("/api/cart/add", methods=["POST"])
def add_to_cart():
    data = request.get_json()

    if not data or "id" not in data:
        return jsonify({"error": "Invalid request"}), 400

    product_id = int(data["id"])

    conn = get_db_connection()
    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (product_id,)
    ).fetchone()
    conn.close()

    if not product:
        return jsonify({"error": "Product not found"}), 404

    if session.get("user_id"):
        conn = get_db_connection()
        conn.execute("""
            INSERT OR IGNORE INTO cart_items (user_id, product_id)
            VALUES (?, ?)
        """, (session["user_id"], product_id))
        conn.commit()
        conn.close()
        return jsonify({"message": "Added", "cart": get_user_cart(session["user_id"])})
    else:
        cart = session.get("cart", [])
        if any(int(item["id"]) == product_id for item in cart):
            return jsonify({"message": "Already in cart", "cart": cart})
        cart.append(dict(product))
        session["cart"] = cart
        return jsonify({"message": "Added", "cart": cart})


@app.route("/api/cart/remove", methods=["POST"])
def remove_from_cart():
    data = request.get_json()

    if not data or "id" not in data:
        return jsonify({"error": "Invalid request"}), 400

    product_id = int(data["id"])

    if session.get("user_id"):
        conn = get_db_connection()
        conn.execute("""
            DELETE FROM cart_items WHERE user_id = ? AND product_id = ?
        """, (session["user_id"], product_id))
        conn.commit()
        conn.close()
        return jsonify({"message": "Removed", "cart": get_user_cart(session["user_id"])})
    else:
        cart = session.get("cart", [])
        cart = [item for item in cart if int(item["id"]) != product_id]
        session["cart"] = cart
        return jsonify({"message": "Removed", "cart": cart})


# ───── OUTFIT BUILDER (AI SUGGEST) ─────
@app.route("/api/outfit/suggest", methods=["POST"])
def suggest_outfit():
    import random
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products WHERE status = 'Available'").fetchall()
    conn.close()
    
    products_list = [dict(p) for p in products]
    
    # Classify into tops and bottoms
    tops = [p for p in products_list if p["category"] in ["Tshirt", "Jacket", "Hoodie"]]
    bottoms = [p for p in products_list if p["category"] in ["Pant", "Dress"]]
    
    combo = []
    if tops:
        combo.append(random.choice(tops))
    if bottoms:
        combo.append(random.choice(bottoms))
        
    tips = [
        "Layer the jacket over the tee for a Thamel streetwear vibe.",
        "A classic retro pairing — simple, sustainable, and chic.",
        "Add a vintage cap or woven bag to complete this Kathmandu look.",
        "Mix the textures: try combining cotton tops with denim bottoms.",
        "Tuck in the shirt for that timeless 90s silhouette."
    ]
    
    return jsonify({
        "items": combo,
        "tip": random.choice(tips) if combo else "Upload some Tops and Bottoms to get outfit recommendations!"
    })


@app.route("/api/ai/tryon/prepare", methods=["POST"])
def prepare_ai_tryon():
    reference_path = save_customer_reference(app.config["UPLOAD_FOLDER"], request.files.get("photo"))

    product_ids = request.form.getlist("product_ids")
    if not product_ids and request.form.get("product_ids"):
        product_ids = [pid.strip() for pid in request.form.get("product_ids", "").split(",") if pid.strip()]

    conn = get_db_connection()
    if product_ids:
        placeholders = ",".join("?" for _ in product_ids)
        products = conn.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})",
            tuple(product_ids)
        ).fetchall()
    else:
        products = conn.execute(
            "SELECT * FROM products WHERE status = 'Available' ORDER BY id DESC LIMIT 8"
        ).fetchall()
    conn.close()

    payload = describe_tryon_plan([dict(product) for product in products])
    payload["reference_photo"] = reference_path
    payload["ready_for_real_ai"] = bool(reference_path and payload["layers"])
    return jsonify(payload)


@app.route("/api/ai/tryon/feedback", methods=["POST"])
def get_ai_tryon_feedback():
    reference_path = None
    equipped_items = []
    gender = "female"
    product_ids = []

    if request.is_json:
        data = request.get_json() or {}
        product_ids = data.get("product_ids", [])
        gender = data.get("gender", "female")
        if not product_ids and "garments" in data:
            categories = data["garments"]
            if categories:
                # Normalize category names to match DB values
                cat_map = {
                    'tshirt': 'Tshirt',
                    't-shirt': 'Tshirt',
                    'pant': 'Pant',
                    'pants': 'Pant',
                    'dress': 'Dress',
                    'jacket': 'Jacket',
                    'hoodie': 'Hoodie',
                    'shoes': 'Shoes',
                    'shoe': 'Shoes',
                }
                conn = get_db_connection()
                for cat in categories:
                    db_cat = cat_map.get(cat.lower(), cat)
                    p = conn.execute("SELECT id, name, category, price, image FROM products WHERE category = ? AND status = 'Available' LIMIT 1", (db_cat,)).fetchone()
                    if p:
                        equipped_items.append(dict(p))
                conn.close()
    else:
        if "photo" in request.files:
            reference_path = save_customer_reference(app.config["UPLOAD_FOLDER"], request.files["photo"])

        product_ids = request.form.getlist("product_ids")
        if not product_ids and request.form.get("product_ids"):
            product_ids = [pid.strip() for pid in request.form.get("product_ids", "").split(",") if pid.strip()]

        gender = request.form.get("gender", "female")

    if gender not in ("male", "female"):
        gender = "female"

    if product_ids:
        conn = get_db_connection()
        placeholders = ",".join("?" for _ in product_ids)
        products = conn.execute(
            f"SELECT id, name, category, price, image FROM products WHERE id IN ({placeholders})",
            tuple(product_ids)
        ).fetchall()
        conn.close()
        equipped_items = [dict(p) for p in products]

    abs_photo_path = None
    if reference_path:
        relative_clean = reference_path.replace("static/", "")
        abs_photo_path = os.path.join(app.root_path, "static", relative_clean)

    feedback_payload = generate_styling_feedback(abs_photo_path, equipped_items, gender)
    return jsonify(feedback_payload)


@app.route("/api/ai/tryon/compose", methods=["POST"])
def ai_compose_tryon():
    """Generate an AI image of the mannequin wearing the selected outfit."""
    product_ids = request.form.getlist("product_ids")
    gender = request.form.get("gender", "female")
    if gender not in ("male", "female"):
        gender = "female"

    if not product_ids:
        return jsonify({"success": False, "error": "No products selected."}), 400

    conn = get_db_connection()
    placeholders = ",".join("?" for _ in product_ids)
    products = conn.execute(
        f"SELECT id, name, category, image, description FROM products WHERE id IN ({placeholders})",
        tuple(product_ids)
    ).fetchall()
    conn.close()

    items = [dict(p) for p in products]
    # Get product image paths for visual reference
    product_images = []
    for item in items:
        if item.get('image'):
            img_path = os.path.join(app.root_path, "static", "uploads", item['image'])
            if os.path.exists(img_path):
                product_images.append(img_path)
    
    # Get the mannequin reference image based on gender
    mannequin_path = None
    if gender == "female":
        mannequin_path = os.path.join(app.root_path, "static", "uploads", "models", "female_base.png")
    else:
        mannequin_path = os.path.join(app.root_path, "static", "uploads", "models", "male_base.png")
    
    # Verify mannequin exists
    if not mannequin_path or not os.path.exists(mannequin_path):
        print(f"[Warning] Mannequin not found: {mannequin_path}")
        mannequin_path = None
    else:
        print(f"[Info] Using mannequin reference: {mannequin_path}")
    
    upload_path = os.path.join(app.root_path, "static", "uploads")
    
    # DEBUG LOG
    print(f"\n[ROUTE DEBUG] About to call compose_outfit_image:")
    print(f"[ROUTE DEBUG]   mannequin_path: {mannequin_path}")
    print(f"[ROUTE DEBUG]   mannequin exists: {os.path.exists(mannequin_path) if mannequin_path else False}")
    print(f"[ROUTE DEBUG]   product_images: {product_images}")
    print(f"[ROUTE DEBUG]   items: {[i.get('name') for i in items]}")
    
    result = compose_outfit_image(items, gender, upload_path, reference_photo_path=mannequin_path, product_images=product_images)
    
    print(f"[ROUTE DEBUG]   result engine: {result.get('engine')}")
    print(f"[ROUTE DEBUG]   result success: {result.get('success')}")
    
    return jsonify(result)



# ───── CHECKOUT ─────
@app.route("/api/checkout", methods=["POST"])
def checkout():
    data = request.get_json()

    if not data or not data.get("name"):
        return jsonify({"error": "Name required"}), 400
        
    if not session.get("user_id"):
        return jsonify({"error": "Authentication required. Please sign in to checkout."}), 401

    user_id = session["user_id"]
    phone = data.get("phone", "").strip()
    location = data.get("location", "").strip()
    payment_method = data.get("method", "card")

    # Get cart items
    cart_items = get_user_cart(user_id)
    if not cart_items:
        return jsonify({"error": "Cart is empty"}), 400

    total_price = sum(item["price"] for item in cart_items)
    items_json = json.dumps(cart_items)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Save details to user profile
    cursor.execute("""
        UPDATE users SET phone = ?, location = ? WHERE id = ?
    """, (phone, location, user_id))

    # Log order
    cursor.execute("""
        INSERT INTO orders (user_id, customer_name, phone, location, total_price, payment_method, items_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, data["name"], phone, location, total_price, payment_method, items_json))

    # Mark products sold
    for item in cart_items:
        cursor.execute("UPDATE products SET status = 'Sold' WHERE id = ?", (item["id"],))

    # Clear database cart
    cursor.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Order confirmed successfully! Your order has been registered for delivery to {location}.",
        "method": payment_method
    })


# ───── VIRTUAL FITTING ROOM (STANDALONE PAGE) ─────
@app.route("/mirror")
def virtual_mirror():
    conn = get_db_connection()
    products = conn.execute(
        "SELECT * FROM products WHERE status = 'Available' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return render_template("virtual_tryon.html", products=products)


# ───── CHATBOT API ─────
@app.route("/api/chatbot", methods=["POST"])
def chatbot():
    data = request.get_json()
    if not data or not data.get("message"):
        return jsonify({"error": "message required"}), 400

    user_message = data["message"].strip()
    history = data.get("history", [])
    gender = data.get("gender", "female")
    product_ids = data.get("product_ids", [])

    equipped_items = []
    if product_ids:
        conn = get_db_connection()
        placeholders = ",".join("?" for _ in product_ids)
        rows = conn.execute(
            f"SELECT id, name, category, price, image FROM products WHERE id IN ({placeholders})",
            tuple(product_ids)
        ).fetchall()
        conn.close()
        equipped_items = [dict(r) for r in rows]

    result = chat_outfit_advisor(user_message, history=history,
                                 equipped_items=equipped_items, gender=gender)
    return jsonify(result)


# ───── REAL-PERSON PHOTO TRY-ON COMPOSE ─────
@app.route("/api/ai/tryon/compose-on-photo", methods=["POST"])
def ai_compose_on_photo():
    """Generate an AI image of the outfit on the user's uploaded photo."""
    product_ids = request.form.getlist("product_ids")
    gender = request.form.get("gender", "female")
    if gender not in ("male", "female"):
        gender = "female"

    photo_file = request.files.get("photo")
    if not photo_file:
        return jsonify({"success": False, "error": "No photo provided."}), 400

    if not product_ids:
        return jsonify({"success": False, "error": "No products selected."}), 400

    # Save the reference photo
    reference_path = save_customer_reference(app.config["UPLOAD_FOLDER"], photo_file)

    conn = get_db_connection()
    placeholders = ",".join("?" for _ in product_ids)
    products = conn.execute(
        f"SELECT id, name, category, image, description FROM products WHERE id IN ({placeholders})",
        tuple(product_ids)
    ).fetchall()
    conn.close()

    items = [dict(p) for p in products]
    
    # Get product image paths for visual reference
    product_images = []
    for item in items:
        if item.get('image'):
            img_path = os.path.join(app.root_path, "static", "uploads", item['image'])
            if os.path.exists(img_path):
                product_images.append(img_path)
    
    # Get absolute photo path
    abs_photo_path = None
    if reference_path:
        relative_clean = reference_path.replace("static/", "")
        abs_photo_path = os.path.join(app.root_path, "static", relative_clean)
    
    # Try to generate with the reference photo for more realistic results
    upload_path = os.path.join(app.root_path, "static", "uploads")
    result = compose_outfit_image(items, gender, upload_path, reference_photo_path=abs_photo_path, product_images=product_images)
    
    # If the main compose failed, try individual API calls with enhanced prompts
    if not result.get("success"):
        outfit_desc = ", ".join([f"{i['name']} ({i['category']})" for i in items])
        
        # Build colored outfit description with specifications
        colored_outfit_parts = []
        clothing_specs = []
        for item in items:
            name = item.get('name', '')
            category = item.get('category', '').lower()
            desc = item.get('description', '')
            color_keywords = ['black', 'white', 'blue', 'red', 'green', 'yellow', 'brown', 'grey', 'gray', 'beige', 'navy', 'olive', 'cream', 'pink', 'purple', 'orange', 'denim', 'khaki']
            item_color = None
            for color in color_keywords:
                if color in name.lower() or (desc and color in desc.lower()):
                    item_color = color
                    break
            colored_name = f"{item_color} {name}" if item_color else name
            colored_outfit_parts.append(colored_name)
            
            # Add specific garment specifications based on name
            if 'pant' in category or 'bottom' in category:
                if 'belly' in name.lower() or 'flare' in name.lower() or 'wide' in name.lower():
                    clothing_specs.append(f"{colored_name}: FLARED/WIDE LEG denim pants, bell-bottom style (NOT skinny/leggings)")
                elif 'jean' in name.lower() or 'denim' in name.lower():
                    clothing_specs.append(f"{colored_name}: denim jeans pants (NOT shorts/underwear)")
                else:
                    clothing_specs.append(f"{colored_name}: FULL LENGTH pants (NOT shorts/underwear)")
            elif 'shirt' in category or 'top' in category or 'tshirt' in category:
                if 'crop' in name.lower() or 'belly' in name.lower() or 'tank' in name.lower():
                    clothing_specs.append(f"{colored_name}: cropped tank top showing midriff")
                else:
                    clothing_specs.append(f"{colored_name}: proper shirt/top")
            else:
                clothing_specs.append(colored_name)
                
        colored_outfit = ", ".join(colored_outfit_parts)
        outfit_specifications = ". ".join(clothing_specs)
        
        # Enhanced prompt specifically for photo mode with natural fitting
        person_prompt = (
            f"Professional fashion photography of a LIGHT-SKINNED {gender} person wearing: {colored_outfit}. "
            f"GARMENT SPECS: {outfit_specifications}. "
            f"CRITICAL: MUST wear {colored_outfit} exactly - "
            f"pants MUST be FULL LENGTH to ankles (NOT shorts, NOT underwear), "
            f"top MUST cover torso (NOT just bra/crop). "
            f"Body has NORMAL proportions, NO elongated limbs. "
            f"Clothes fit with tailored silhouette, realistic fabric, "
            f"full body visible, studio lighting, plain background."
        )
        
        replicate_key = os.environ.get("REPLICATE_API_TOKEN")
        together_key = os.environ.get("TOGETHER_API_KEY")
        hf_key = os.environ.get("HUGGINGFACE_API_KEY")
        import requests as req
        import urllib.parse
        
        # Try Replicate first (HIGH QUALITY)
        if replicate_key:
            try:
                print("[PhotoCompose] Trying Replicate FLUX...")
                import replicate
                client = replicate.Client(api_token=replicate_key)
                output = client.run(
                    "black-forest-labs/flux-1-schnell",
                    input={
                        "prompt": person_prompt,
                        "aspect_ratio": "1:1",
                        "output_format": "jpg",
                        "output_quality": 80,
                        "num_inference_steps": 4,
                    }
                )
                if output:
                    img_bytes = output.read() if hasattr(output, 'read') else output
                    if isinstance(img_bytes, str):
                        img_resp = requests.get(img_bytes, timeout=60)
                        img_bytes = img_resp.content
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    return jsonify({"success": True, "image": f"data:image/jpeg;base64,{b64}", "engine": "Replicate FLUX"})
            except Exception as e:
                print(f"[PhotoCompose] Replicate error: {e}")
        
        # Try Pollinations.ai (FREE fallback)
        try:
            print("[PhotoCompose] Trying Pollinations.ai (FREE)...")
            encoded_prompt = urllib.parse.quote(person_prompt)
            pollinations_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed=42&nologo=true&model=turbo"
            resp = req.get(pollinations_url, timeout=120)
            if resp.status_code == 200:
                b64 = base64.b64encode(resp.content).decode("utf-8")
                return jsonify({"success": True, "image": f"data:image/jpeg;base64,{b64}", "engine": "Pollinations.ai (FREE)"})
        except Exception as e:
            print(f"[PhotoCompose] Pollinations error: {e}")
        
        if together_key:
            try:
                resp = req.post(
                    "https://api.together.xyz/v1/images/generations",
                    headers={"Authorization": f"Bearer {together_key}", "Content-Type": "application/json"},
                    json={
                        "model": "black-forest-labs/FLUX.1-schnell-Free",
                        "prompt": person_prompt,
                        "width": 1024, "height": 1024,
                        "steps": 4, "n": 1,
                        "response_format": "b64_json"
                    },
                    timeout=90
                )
                if resp.status_code == 200:
                    b64 = resp.json()["data"][0]["b64_json"]
                    return jsonify({"success": True, "image": f"data:image/jpeg;base64,{b64}", "engine": "Together AI FLUX"})
            except Exception as e:
                print(f"[PhotoCompose] Together AI error: {e}")
        
        if hf_key:
            try:
                HF_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
                resp = req.post(HF_URL, headers={"Authorization": f"Bearer {hf_key}"},
                               json={"inputs": person_prompt, "parameters": {"num_inference_steps": 4}}, timeout=60)
                if resp.status_code == 200:
                    b64 = base64.b64encode(resp.content).decode("utf-8")
                    return jsonify({"success": True, "image": f"data:image/jpeg;base64,{b64}", "engine": "HuggingFace FLUX"})
            except Exception as e:
                print(f"[PhotoCompose] HuggingFace error: {e}")
    
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
