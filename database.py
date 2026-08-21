
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "database" / "om_kirana.db"

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category_id INTEGER,
        price REAL NOT NULL DEFAULT 0,
        purchase_price REAL NOT NULL DEFAULT 0,
        stock INTEGER NOT NULL DEFAULT 0,
        unit TEXT DEFAULT '',
        barcode TEXT DEFAULT '',
        image TEXT DEFAULT '',
        description TEXT DEFAULT '',
        offer TEXT DEFAULT '',
        featured INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(category_id) REFERENCES categories(id)
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        note TEXT DEFAULT '',
        total REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'Received',
        delivery_type TEXT DEFAULT 'Pickup',
        address TEXT DEFAULT '',
        payment_method TEXT DEFAULT 'Pay at Store',
        coupon_code TEXT DEFAULT '',
        discount REAL DEFAULT 0,
        loyalty_earned INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY(order_id) REFERENCES orders(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    );
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL UNIQUE,
        loyalty_points INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        channel TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'Pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS order_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_phone TEXT NOT NULL,
        product_id INTEGER NOT NULL,
        UNIQUE(customer_phone,product_id)
    );
    CREATE TABLE IF NOT EXISTS login_codes (
        phone TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        discount_percent REAL DEFAULT 0,
        ends_at TEXT,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        discount_percent REAL DEFAULT 0,
        max_discount REAL DEFAULT 0,
        min_order REAL DEFAULT 0,
        active INTEGER DEFAULT 1,
        expires_at TEXT
    );
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount REAL NOT NULL DEFAULT 0,
        category TEXT DEFAULT 'Other',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        customer_name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        rating INTEGER NOT NULL,
        text TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS price_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL UNIQUE,
        margin_percent REAL DEFAULT 10,
        auto_update INTEGER DEFAULT 1,
        last_purchase_price REAL DEFAULT 0,
        last_selling_price REAL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        old_purchase REAL, new_purchase REAL,
        old_price REAL, new_price REAL,
        reason TEXT DEFAULT 'Manual', created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notification_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL,
        phone TEXT DEFAULT '',
        sms INTEGER DEFAULT 1,
        whatsapp INTEGER DEFAULT 1,
        email INTEGER DEFAULT 0,
        daily_report INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS saved_addresses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_phone TEXT NOT NULL,
        label TEXT DEFAULT 'Home',
        address TEXT NOT NULL,
        is_default INTEGER DEFAULT 0
    );
    """)
    # Safe upgrades for databases from earlier phases.
    upgrades = {
        "products": [
            ("purchase_price", "REAL NOT NULL DEFAULT 0"),
            ("barcode", "TEXT DEFAULT ''"),
            ("description", "TEXT DEFAULT ''"),
            ("offer", "TEXT DEFAULT ''")
        ],
        "orders": [
            ("delivery_type", "TEXT DEFAULT 'Pickup'"),
            ("address", "TEXT DEFAULT ''"),
            ("payment_method", "TEXT DEFAULT 'Pay at Store'"),
            ("coupon_code", "TEXT DEFAULT ''"),
            ("discount", "REAL DEFAULT 0"),
            ("loyalty_earned", "INTEGER DEFAULT 0")
        ],
        "customers": [("loyalty_points", "INTEGER DEFAULT 0")]
    }
    for table, cols in upgrades.items():
        existing = {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, spec in cols:
            if col not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {spec}")

    defaults = {
        "store_phone":"","whatsapp":"","address":"","upi_id":"","public_url":"",
        "opening_time":"08:00","closing_time":"21:00","delivery_charge":"0",
        "low_stock_limit":"10","store_name":"OM KIRANA STORE",
        "default_margin_percent":"12","notify_owner_phone":"","notify_whatsapp":"",
        "daily_report_time":"21:00","auto_price_updates":"1"
    }
    for k,v in defaults.items():
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)",(k,v))
    db.commit()
    db.close()

def seed_products():
    db = get_db()
    categories = [
        "Atta & Flour","Rice","Pulses & Dals","Oil & Ghee","Spices & Masala",
        "Dry Fruits & Nuts","Biscuits & Bakery","Namkeen & Snacks","Beverages & Cold Drinks",
        "Dairy & Eggs","Instant Food & Noodles","Breakfast & Cereals","Sauces & Spreads",
        "Sweets & Chocolates","Personal Care","Cleaning & Household","Pooja & Stationery",
        "Baby Care","Pet Care","Frozen & Ice Cream","Other"
    ]
    for name in categories:
        db.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (name,))
    count = db.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
    if count == 0:
        cat={r["name"]:r["id"] for r in db.execute("SELECT id,name FROM categories").fetchall()}
        products = []
        def add(name, category, price, purchase, stock, unit, barcode, image, desc, offer=""):
            products.append((name,cat[category],price,purchase,stock,unit,barcode,image,desc,offer))
        items = [
        ("Aashirvaad Atta","Atta & Flour",280,220,35,"5 KG","890100000001","atta","Premium whole wheat flour"),
        ("Fortune Chakki Fresh Atta","Atta & Flour",285,225,30,"5 KG","890100000002","atta","Fresh chakki wheat flour"),
        ("Besan","Atta & Flour",95,75,25,"500 G","890100000003","besan","Fine gram flour"),
        ("Maida","Atta & Flour",48,38,25,"500 G","890100000004","flour","Refined wheat flour"),
        ("Suji","Atta & Flour",55,43,25,"500 G","890100000005","suji","Semolina for breakfast and sweets"),
        ("India Gate Basmati Rice","Rice",150,125,25,"1 KG","890100000006","rice","Premium basmati rice"),
        ("Daawat Basmati Rice","Rice",180,150,20,"1 KG","890100000007","rice","Long grain basmati rice"),
        ("Sona Masoori Rice","Rice",72,58,30,"1 KG","890100000008","rice","Everyday rice"),
        ("Arhar Dal","Pulses & Dals",145,118,28,"1 KG","890100000009","dal","Toor/arhar dal"),
        ("Moong Dal","Pulses & Dals",135,108,25,"1 KG","890100000010","dal","Yellow moong dal"),
        ("Masoor Dal","Pulses & Dals",105,84,25,"1 KG","890100000011","dal","Red lentils"),
        ("Chana Dal","Pulses & Dals",95,76,25,"1 KG","890100000012","dal","Split chickpeas"),
        ("Fortune Sunflower Oil","Oil & Ghee",145,123,30,"1 L","890100000013","oil","Refined sunflower cooking oil"),
        ("Fortune Mustard Oil","Oil & Ghee",155,130,28,"1 L","890100000014","oil","Cold-pressed style mustard oil"),
        ("Amul Ghee","Oil & Ghee",650,570,18,"1 L","890100000015","ghee","Pure dairy ghee"),
        ("Tata Salt","Spices & Masala",28,22,60,"1 KG","890100000016","salt","Iodised salt"),
        ("MDH Garam Masala","Spices & Masala",75,58,20,"100 G","890100000017","masala","Aromatic garam masala"),
        ("Everest Chaat Masala","Spices & Masala",65,50,20,"100 G","890100000018","masala","Tangy chaat masala"),
        ("Turmeric Powder","Spices & Masala",55,42,30,"100 G","890100000019","turmeric","Pure haldi powder"),
        ("Red Chilli Powder","Spices & Masala",60,46,30,"100 G","890100000020","chilli","Red chilli powder"),
        ("Almonds","Dry Fruits & Nuts",180,145,20,"200 G","890100000021","almonds","Premium almonds"),
        ("Cashews","Dry Fruits & Nuts",210,170,18,"200 G","890100000022","cashew","Premium cashew nuts"),
        ("Raisins","Dry Fruits & Nuts",110,85,22,"200 G","890100000023","raisins","Golden raisins"),
        ("Walnuts","Dry Fruits & Nuts",260,210,15,"200 G","890100000024","walnut","Crunchy walnut kernels"),
        ("Pistachios","Dry Fruits & Nuts",240,195,15,"200 G","890100000025","pistachio","Roasted pistachios"),
        ("Parle-G Biscuits","Biscuits & Bakery",10,7,80,"Pack","890100000026","biscuits","Classic glucose biscuits"),
        ("Britannia Good Day","Biscuits & Bakery",30,23,60,"Pack","890100000027","biscuits","Crunchy butter cookies"),
        ("Oreo","Biscuits & Bakery",40,32,60,"Pack","890100000028","biscuits","Chocolate sandwich biscuits"),
        ("Marie Gold","Biscuits & Bakery",30,23,55,"Pack","890100000029","biscuits","Light tea-time biscuits"),
        ("Bread","Biscuits & Bakery",35,28,25,"1 Pack","890100000030","bread","Fresh sandwich bread"),
        ("Haldiram's Aloo Bhujia","Namkeen & Snacks",60,48,45,"200 G","890100000031","namkeen","Spicy crunchy snack"),
        ("Balaji Wafers","Namkeen & Snacks",20,15,70,"Pack","890100000032","chips","Potato wafers"),
        ("Kurkure Masala Munch","Namkeen & Snacks",20,15,70,"Pack","890100000033","chips","Masala corn snack"),
        ("Lays Magic Masala","Namkeen & Snacks",20,15,70,"Pack","890100000034","chips","Classic masala chips"),
        ("Coca-Cola","Beverages & Cold Drinks",40,32,50,"750 ML","890100000035","cola","Chilled soft drink"),
        ("Pepsi","Beverages & Cold Drinks",40,32,50,"750 ML","890100000036","cola","Refreshing cola"),
        ("Sprite","Beverages & Cold Drinks",40,32,50,"750 ML","890100000037","lemon","Lemon-lime soft drink"),
        ("Thums Up","Beverages & Cold Drinks",40,32,50,"750 ML","890100000038","cola","Strong cola drink"),
        ("Real Fruit Juice","Beverages & Cold Drinks",120,98,25,"1 L","890100000039","juice","Mixed fruit juice"),
        ("Tata Tea Gold","Beverages & Cold Drinks",150,118,25,"250 G","890100000040","tea","Premium tea"),
        ("Nescafe Classic","Beverages & Cold Drinks",165,135,20,"50 G","890100000041","coffee","Instant coffee"),
        ("Amul Milk","Dairy & Eggs",34,29,40,"500 ML","890100000042","milk","Fresh dairy milk"),
        ("Amul Curd","Dairy & Eggs",35,29,30,"400 G","890100000043","curd","Fresh curd"),
        ("Amul Butter","Dairy & Eggs",60,51,25,"100 G","890100000044","butter","Pasteurised butter"),
        ("Amul Cheese","Dairy & Eggs",140,120,18,"200 G","890100000045","cheese","Cheese slices/block"),
        ("Fresh Eggs","Dairy & Eggs",72,60,30,"6 Eggs","890100000046","eggs","Farm fresh eggs"),
        ("Maggi 2-Minute Noodles","Instant Food & Noodles",14,10,80,"Pack","890100000047","noodles","Instant masala noodles"),
        ("Yippee Noodles","Instant Food & Noodles",20,15,60,"Pack","890100000048","noodles","Instant noodles"),
        ("Poha","Breakfast & Cereals",65,50,30,"500 G","890100000049","poha","Flattened rice"),
        ("Corn Flakes","Breakfast & Cereals",180,150,18,"300 G","890100000050","cereal","Crispy corn flakes"),
        ("Kellogg's Chocos","Breakfast & Cereals",220,185,18,"250 G","890100000051","cereal","Chocolate cereal"),
        ("Kissan Tomato Ketchup","Sauces & Spreads",120,95,25,"500 G","890100000052","ketchup","Tomato ketchup"),
        ("Maggi Hot & Sweet Sauce","Sauces & Spreads",95,76,20,"500 G","890100000053","ketchup","Hot and sweet sauce"),
        ("Nutella","Sauces & Spreads",210,175,12,"350 G","890100000054","spread","Hazelnut cocoa spread"),
        ("Cadbury Dairy Milk","Sweets & Chocolates",50,40,80,"55 G","890100000055","chocolate","Milk chocolate"),
        ("KitKat","Sweets & Chocolates",40,32,70,"41.5 G","890100000056","chocolate","Crispy wafer chocolate"),
        ("5 Star","Sweets & Chocolates",20,15,70,"Pack","890100000057","chocolate","Caramel chocolate"),
        ("Haldiram Gulab Jamun","Sweets & Chocolates",180,150,12,"1 KG","890100000058","sweet","Ready-to-serve gulab jamun"),
        ("Dove Shampoo","Personal Care",190,155,20,"180 ML","890100000059","shampoo","Daily hair care shampoo"),
        ("Clinic Plus Shampoo","Personal Care",120,98,25,"175 ML","890100000060","shampoo","Family shampoo"),
        ("Dove Soap","Personal Care",55,43,30,"100 G","890100000061","soap","Moisturising bathing soap"),
        ("Lux Soap","Personal Care",40,31,35,"100 G","890100000062","soap","Bathing soap"),
        ("Colgate Toothpaste","Personal Care",95,75,35,"150 G","890100000063","toothpaste","Fluoride toothpaste"),
        ("Closeup Toothpaste","Personal Care",90,72,30,"150 G","890100000064","toothpaste","Fresh gel toothpaste"),
        ("Head & Shoulders","Personal Care",210,175,18,"180 ML","890100000065","shampoo","Anti-dandruff shampoo"),
        ("Dettol Handwash","Personal Care",110,88,25,"250 ML","890100000066","handwash","Hand cleansing wash"),
        ("Surf Excel Matic","Cleaning & Household",210,170,20,"1 KG","890100000067","detergent","Laundry detergent"),
        ("Vim Dishwash Liquid","Cleaning & Household",125,100,25,"500 ML","890100000068","dishwash","Dishwashing liquid"),
        ("Harpic Toilet Cleaner","Cleaning & Household",105,84,22,"500 ML","890100000069","cleaner","Toilet cleaning liquid"),
        ("Lizol Floor Cleaner","Cleaning & Household",145,115,22,"500 ML","890100000070","cleaner","Floor disinfectant"),
        ("Colin Glass Cleaner","Cleaning & Household",110,88,20,"500 ML","890100000071","cleaner","Glass and surface cleaner"),
        ("Good Knight Refill","Cleaning & Household",85,68,30,"1 Refill","890100000072","repellent","Mosquito repellent refill"),
        ("Agarbatti","Pooja & Stationery",45,34,25,"1 Pack","890100000073","pooja","Fragrant incense sticks"),
        ("Camphor","Pooja & Stationery",70,55,20,"50 G","890100000074","pooja","Puja camphor"),
        ("Ball Pen","Pooja & Stationery",10,6,80,"1 Pc","890100000075","pen","Smooth writing pen"),
        ("Notebook","Pooja & Stationery",45,35,35,"1 Pc","890100000076","notebook","Ruled notebook"),
        ("Pampers Diapers","Baby Care",299,255,15,"Pack","890100000077","diaper","Baby diapers"),
        ("Johnson's Baby Powder","Baby Care",130,105,15,"200 G","890100000078","baby","Baby care powder"),
        ("Baby Wipes","Baby Care",120,95,20,"Pack","890100000079","wipes","Gentle baby wipes"),
        ("Pedigree Dog Food","Pet Care",260,220,12,"1 KG","890100000080","pet","Dog food"),
        ("Whiskas Cat Food","Pet Care",180,150,12,"450 G","890100000081","pet","Cat food"),
        ("Amul Ice Cream","Frozen & Ice Cream",120,95,15,"500 ML","890100000082","icecream","Frozen dairy ice cream"),
        ("Frozen Peas","Frozen & Ice Cream",140,115,15,"500 G","890100000083","peas","Frozen green peas"),
        ("Vanaspati","Oil & Ghee",130,105,15,"1 KG","890100000084","oil","Vegetable cooking fat"),
        ("Rajma","Pulses & Dals",145,115,20,"1 KG","890100000085","rajma","Red kidney beans"),
        ("Kabuli Chana","Pulses & Dals",120,95,22,"1 KG","890100000086","chana","White chickpeas"),
        ("Black Pepper","Spices & Masala",90,70,20,"50 G","890100000087","pepper","Whole black pepper"),
        ("Cumin Seeds","Spices & Masala",65,50,25,"100 G","890100000088","cumin","Whole jeera"),
        ("Cardamom","Dry Fruits & Nuts",150,120,12,"25 G","890100000089","cardamom","Green cardamom"),
        ("Dates","Dry Fruits & Nuts",180,145,18,"250 G","890100000090","dates","Soft dates"),
        ("Makhana","Dry Fruits & Nuts",160,125,18,"100 G","890100000091","makhana","Roasted fox nuts"),
        ("Roasted Peanuts","Namkeen & Snacks",55,43,30,"200 G","890100000092","peanuts","Roasted salted peanuts"),
        ("Coconut Biscuits","Biscuits & Bakery",35,27,45,"Pack","890100000093","biscuits","Coconut biscuits"),
        ("Frooti","Beverages & Cold Drinks",20,15,60,"600 ML","890100000094","juice","Mango drink"),
        ("Limca","Beverages & Cold Drinks",40,32,40,"750 ML","890100000095","lemon","Lemon soft drink"),
        ("Red Bull","Beverages & Cold Drinks",125,105,15,"250 ML","890100000096","energy","Energy drink"),
        ("Rooh Afza","Beverages & Cold Drinks",160,130,15,"750 ML","890100000097","syrup","Rose sharbat"),
        ("Amul Lassi","Dairy & Eggs",30,24,30,"200 ML","890100000098","lassi","Chilled sweet lassi"),
        ("Paneer","Dairy & Eggs",110,92,15,"200 G","890100000099","paneer","Fresh paneer"),
        ("Corn Flour","Atta & Flour",55,42,20,"100 G","890100000100","flour","Corn starch"),
        ]
        for row in items: add(*row)
        db.executemany("""INSERT INTO products
        (name,category_id,price,purchase_price,stock,unit,barcode,image,description,offer)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",products)
    db.commit(); db.close()
