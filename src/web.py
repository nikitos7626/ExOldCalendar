"""Веб-интерфейс для ExCalendar (Flask)"""

from flask import Flask, render_template, jsonify, request

from .booking_store import BookingStore
from .config import load_settings

app = Flask(__name__)

# Загружаем настройки
settings = load_settings()
app.secret_key = settings.flask_secret_key

# Инициализируем хранилище
store = BookingStore(settings=settings)


@app.route('/')
def index():
    """Главная страница - календарь для клиентов"""
    return render_template('index.html')


@app.route('/api/slots')
def get_slots():
    """Получить доступные слоты"""
    from datetime import datetime, timedelta
    import pytz
    
    tz = pytz.timezone(settings.timezone)
    today = datetime.now(tz).date()
    
    # Получаем все существующие записи
    all_requests = store.list_all_requests()
    
    # Генерируем рабочие слоты на ближайшие дни
    slots = []
    for i in range(settings.booking_horizon_days):
        current_date = today + timedelta(days=i)
        if current_date.weekday() not in settings.workdays:
            continue
            
        for hour in range(settings.work_start_hour, settings.work_end_hour):
            time_str = f"{hour:02d}:00"
            slot_status = "free"
            
            # Проверяем статус слота
            for req in all_requests:
                if req.date == current_date.isoformat() and req.time == time_str:
                    if req.status in ("pending", "confirmed"):
                        slot_status = req.status
                        break
            
            slots.append({
                "date": current_date.isoformat(),
                "time": time_str,
                "status": slot_status
            })
    
    return jsonify(slots)


@app.route('/api/bookings')
def get_bookings():
    """Получить все бронирования (для админа)"""
    all_requests = store.list_all_requests()
    
    bookings = []
    for req in all_requests:
        if req.status in ("pending", "confirmed"):
            bookings.append({
                "id": req.id,
                "date": req.date,
                "time": req.time,
                "status": req.status,
                "client": req.full_name,
                "username": req.username,
                "created_at": req.created_at
            })
    
    return jsonify(bookings)


@app.route('/admin')
def admin():
    """Админ-панель"""
    return render_template('admin.html')


@app.route('/api/cancel', methods=['POST'])
def cancel_booking():
    """Отменить бронирование"""
    data = request.get_json()
    booking_id = data.get('booking_id')
    
    if not booking_id:
        return jsonify({'error': 'booking_id required'}), 400
    
    try:
        store.update_status(booking_id, 'cancelled_by_trainer')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/book', methods=['POST'])
def create_booking():
    """Создать бронирование (из веб-интерфейса)"""
    data = request.get_json()
    
    required_fields = ['user_id', 'full_name', 'date', 'time']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'{field} required'}), 400
    
    try:
        booking = store.create_request(
            user_id=int(data['user_id']),
            username=data.get('username', ''),
            full_name=data['full_name'],
            date_str=data['date'],
            time_str=data['time']
        )
        return jsonify({'success': True, 'booking_id': booking.id})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def run_web():
    """Запуск веб-сервера"""
    app.run(
        host=settings.flask_host,
        port=settings.flask_port,
        debug=False
    )


if __name__ == '__main__':
    run_web()
