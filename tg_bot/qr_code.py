import qrcode
from io import BytesIO
import base64

def generate_telegram_qr(bot_username, user_email):
    """
    Генерирует QR-код с универсальной ссылкой на Telegram бота
    """
    # Универсальная ссылка, которая работает и в браузере, и в Telegram
    bot_link = f"https://t.me/{bot_username}"  # Просто ссылка на бота, без параметров

    # Альтернатива: можно использовать ссылку на Telegram web
    # bot_link = f"https://telegram.me/{bot_username}?start={user_email}"

    # Создаем QR-код
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=5
    )
    qr.add_data(bot_link)
    qr.make(fit=True)

    # Создаем изображение
    img = qr.make_image(fill_color="black", back_color="white")

    # Конвертируем в base64
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return img_str
