"""
Telegram бот для выдачи реферальных ссылок
Версия для деплоя на Render.com (webhook) — ПОЛНОСТЬЮ РАБОЧАЯ
"""

import os
import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import pandas as pd
import telebot
from telebot import types
from flask import Flask, request

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8755780244:AAE2PG3ExVZ4Z-Hpd2iblESfdC02YfTG5pc')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '7842146773'))
ADMIN_CONTACT = os.environ.get('ADMIN_CONTACT', 'WhyNotToDoThis')
EXCEL_FILE = os.environ.get('EXCEL_FILE', 'offers.xlsx')

logger.info(f"🚀 Запуск бота. TOKEN={'*' * 10}, ADMIN_ID={ADMIN_ID}")

# ==================== МОДЕЛИ ДАННЫХ ====================
@dataclass
class Offer:
    """Модель данных офера"""
    name: str
    reward: str
    conditions: str
    link: str
    type: str = ''
    full_payment: str = ''
    payment: str = ''

    def is_valid(self) -> bool:
        return bool(self.name and self.link)

    def to_display_text(self) -> str:
        """Форматирование для отображения"""
        if self.type == '+':
            type_emoji = "💼"
            type_text = "Бизнес-офер"
        else:
            type_emoji = "🏦"
            type_text = "Офер"

        text_parts = [f"{type_emoji} <b>{type_text}:</b> {self.name}"]

        if self.reward:
            text_parts.append(f"💰 <b>Вознаграждение:</b> {self.reward} руб")

        if self.conditions:
            text_parts.append(f"📋 <b>Условия:</b> {self.conditions}")

        text_parts.append(f"\n🔗 <b>Ссылка:</b> {self.link}")

        return "\n".join(text_parts)


@dataclass
class OfferGroup:
    """Модель группы оферов"""
    name: str
    offers: List[Offer]

    def __post_init__(self):
        self.offers = [offer for offer in self.offers if offer.is_valid()]

    @property
    def offers_count(self) -> int:
        return len(self.offers)

    def get_offer(self, index: int) -> Optional[Offer]:
        if 0 <= index < len(self.offers):
            return self.offers[index]
        return None


# ==================== ПАРСЕР EXCEL ====================
class ExcelOfferParser:
    """Парсер оферов из Excel файла"""

    RKO_COLUMNS = ['Оферы', 'Выплата', 'Вознаграждение', 'Условия', 'Ссылка', 'Тип']
    RKO_MAPPING = {
        'Оферы': 'name',
        'Выплата': 'payment',
        'Вознаграждение': 'reward',
        'Условия': 'conditions',
        'Ссылка': 'link',
        'Тип': 'type'
    }

    OTHER_COLUMNS = ['Оферы', 'Выплата 100%', 'Вознаграждение', 'Условия', 'Ссылка']
    OTHER_MAPPING = {
        'Оферы': 'name',
        'Выплата 100%': 'full_payment',
        'Вознаграждение': 'reward',
        'Условия': 'conditions',
        'Ссылка': 'link'
    }

    def __init__(self, file_path: str):
        self.file_path = file_path

    def parse(self) -> Dict[str, OfferGroup]:
        """Парсинг Excel файла"""
        try:
            if not os.path.exists(self.file_path):
                logger.error(f"❌ Файл {self.file_path} не найден!")
                return {}
                
            excel_file = pd.ExcelFile(self.file_path)
            groups = {}

            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(self.file_path, sheet_name=sheet_name)

                if self._is_rko_table(df):
                    offers = self._parse_rko_offers(df)
                else:
                    offers = self._parse_other_offers(df)

                group_name = self._get_group_name_with_emoji(sheet_name)
                if offers:
                    groups[group_name] = OfferGroup(
                        name=group_name,
                        offers=offers
                    )
                    logger.info(f"✅ Загружена группа '{group_name}' с {len(offers)} оферами")

            logger.info(f"📊 Всего загружено групп: {len(groups)}")
            return groups

        except Exception as e:
            logger.error(f"❌ Ошибка при парсинге Excel: {e}")
            return {}

    def _is_rko_table(self, df: pd.DataFrame) -> bool:
        return 'Тип' in df.columns

    def _parse_rko_offers(self, df: pd.DataFrame) -> List[Offer]:
        offers = []
        available_columns = [col for col in self.RKO_COLUMNS if col in df.columns]

        for _, row in df.iterrows():
            offer_data = {}
            for col in available_columns:
                if col in self.RKO_MAPPING:
                    value = row[col] if pd.notna(row[col]) else ''
                    offer_data[self.RKO_MAPPING[col]] = str(value)

            for field in ['name', 'payment', 'reward', 'conditions', 'link', 'type']:
                if field not in offer_data:
                    offer_data[field] = ''

            offer = Offer(**offer_data)
            if offer.is_valid():
                offers.append(offer)

        return offers

    def _parse_other_offers(self, df: pd.DataFrame) -> List[Offer]:
        offers = []
        available_columns = [col for col in self.OTHER_COLUMNS if col in df.columns]

        for _, row in df.iterrows():
            offer_data = {}
            for col in available_columns:
                if col in self.OTHER_MAPPING:
                    value = row[col] if pd.notna(row[col]) else ''
                    offer_data[self.OTHER_MAPPING[col]] = str(value)

            for field in ['name', 'full_payment', 'reward', 'conditions', 'link']:
                if field not in offer_data:
                    offer_data[field] = ''

            offer_data['type'] = ''
            offer_data['payment'] = ''

            offer = Offer(**offer_data)
            if offer.is_valid():
                offers.append(offer)

        return offers

    def _get_group_name_with_emoji(self, sheet_name: str) -> str:
        sheet_lower = sheet_name.lower()

        if 'рко' in sheet_lower:
            return f"🏦 {sheet_name}"
        elif 'кредит' in sheet_lower:
            return f"💳 {sheet_name}"
        elif 'дебет' in sheet_lower or 'карт' in sheet_lower:
            return f"💳 {sheet_name}"
        elif 'вклад' in sheet_lower:
            return f"💰 {sheet_name}"
        elif 'инвест' in sheet_lower:
            return f"📈 {sheet_name}"
        elif 'страх' in sheet_lower:
            return f"🛡️ {sheet_name}"
        else:
            return f"📋 {sheet_name}"


# ==================== РЕПОЗИТОРИЙ ====================
class ExcelOfferRepository:
    """Репозиторий оферов на основе Excel файла"""

    def __init__(self, file_path: str, parser: ExcelOfferParser):
        self.file_path = file_path
        self.parser = parser
        self._groups: Dict[str, OfferGroup] = {}
        self._last_load_time = 0
        self._cache_ttl = 300

    def load_offers(self) -> Dict[str, OfferGroup]:
        current_time = time.time()

        if not self._groups or (current_time - self._last_load_time) > self._cache_ttl:
            self._groups = self.parser.parse()
            self._last_load_time = current_time

        return self._groups

    def reload(self) -> bool:
        try:
            self._groups = self.parser.parse()
            self._last_load_time = time.time()
            return True
        except Exception as e:
            logger.error(f"Ошибка при перезагрузке: {e}")
            return False

    def get_groups(self) -> List[str]:
        return list(self.load_offers().keys())

    def get_group(self, name: str) -> Optional[OfferGroup]:
        return self.load_offers().get(name)


# ==================== ФАБРИКА CALLBACK ====================
class CallbackFactory:
    MAIN_MENU = "main_menu"
    CONTACT_ADMIN = "contact_admin"
    GROUP_PREFIX = "group"
    OFFER_PREFIX = "offer"
    PAGE_PREFIX = "page"

    @classmethod
    def group(cls, group_name: str) -> str:
        return f"{cls.GROUP_PREFIX}|{group_name}"

    @classmethod
    def offer(cls, group_name: str, index: int) -> str:
        return f"{cls.OFFER_PREFIX}|{group_name}|{index}"

    @classmethod
    def page(cls, group_name: str, page: int) -> str:
        return f"{cls.PAGE_PREFIX}|{group_name}|{page}"

    @classmethod
    def parse(cls, callback_data: str) -> Dict[str, Any]:
        parts = callback_data.split('|')

        if len(parts) == 1:
            return {'type': parts[0]}
        elif len(parts) == 2:
            return {'type': parts[0], 'group_name': parts[1]}
        elif len(parts) == 3:
            return {
                'type': parts[0],
                'group_name': parts[1],
                'value': parts[2]
            }
        return {'type': 'unknown'}


# ==================== КЛАВИАТУРЫ ====================
class OfferKeyboardBuilder:
    def __init__(self, repository: ExcelOfferRepository, admin_contact: Optional[str] = None):
        self.repository = repository
        self.admin_contact = admin_contact
        self.items_per_page = 5

    def build_main_keyboard(self) -> types.InlineKeyboardMarkup:
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for group_name in self.repository.get_groups():
            button = types.InlineKeyboardButton(
                text=f"{group_name}",
                callback_data=CallbackFactory.group(group_name)
            )
            keyboard.add(button)

        if self.admin_contact:
            username = self.admin_contact.replace('@', '')
            contact_button = types.InlineKeyboardButton(
                text="📞 Связь с администратором",
                url=f"https://t.me/{username}"
            )
        else:
            contact_button = types.InlineKeyboardButton(
                text="📞 Связь с администратором",
                callback_data=CallbackFactory.CONTACT_ADMIN
            )
        keyboard.add(contact_button)

        return keyboard

    def build_group_keyboard(self, group_name: str, page: int = 0) -> types.InlineKeyboardMarkup:
        keyboard = types.InlineKeyboardMarkup(row_width=1)

        group = self.repository.get_group(group_name)
        if not group:
            return keyboard

        start_idx = page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, group.offers_count)

        for i in range(start_idx, end_idx):
            offer = group.offers[i]

            if offer.type == '+':
                type_emoji = "💼"
            elif 'рко' in group_name.lower():
                type_emoji = "🏦"
            else:
                type_emoji = "📋"

            if offer.reward:
                button_text = f"{type_emoji} {offer.name} - {offer.reward} руб"
            else:
                button_text = f"{type_emoji} {offer.name}"

            if len(button_text) > 40:
                button_text = button_text[:37] + "..."

            button = types.InlineKeyboardButton(
                text=button_text,
                callback_data=CallbackFactory.offer(group_name, i)
            )
            keyboard.add(button)

        total_pages = (group.offers_count + self.items_per_page - 1) // self.items_per_page
        nav_buttons = []

        if page > 0:
            nav_buttons.append(types.InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=CallbackFactory.page(group_name, page - 1)
            ))

        if page < total_pages - 1:
            nav_buttons.append(types.InlineKeyboardButton(
                text="Вперед ▶️",
                callback_data=CallbackFactory.page(group_name, page + 1)
            ))

        if nav_buttons:
            keyboard.row(*nav_buttons)

        keyboard.add(types.InlineKeyboardButton(
            text="🏠 Главное меню",
            callback_data=CallbackFactory.MAIN_MENU
        ))

        return keyboard

    def build_offer_keyboard(self, group_name: str, offer: Offer) -> types.InlineKeyboardMarkup:
        keyboard = types.InlineKeyboardMarkup(row_width=1)

        if self.admin_contact:
            username = self.admin_contact.replace('@', '')
            admin_button = types.InlineKeyboardButton(
                text="📞 Связь с администратором",
                url=f"https://t.me/{username}"
            )
        else:
            admin_button = types.InlineKeyboardButton(
                text="📞 Связь с администратором",
                callback_data=CallbackFactory.CONTACT_ADMIN
            )
        keyboard.add(admin_button)

        keyboard.add(types.InlineKeyboardButton(
            text="◀️ Назад к списку",
            callback_data=CallbackFactory.group(group_name)
        ))

        return keyboard


# ==================== ИНИЦИАЛИЗАЦИЯ РЕПОЗИТОРИЯ ====================
parser = ExcelOfferParser(EXCEL_FILE)
repository = ExcelOfferRepository(EXCEL_FILE, parser)

# Загружаем данные при старте
groups = repository.load_offers()
logger.info(f"📊 Загружено групп: {len(groups)}")

keyboard_builder = OfferKeyboardBuilder(repository, ADMIN_CONTACT)

# ==================== СОЗДАНИЕ БОТА ====================
bot = telebot.TeleBot(TOKEN)
logger.info("✅ Бот создан")


# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    logger.info(f"🔥 Получена команда /start от пользователя {user_id}")
    
    try:
        welcome_text = """Здарова, охотник за халявой! 🤝

Ты зашел по адресу. Если хочешь понять, как забрать у банка 18 тысяч рублей на старте, экономить по 10-15к в месяц и при этом не вникать в это все с нуля— ты попал куда надо.

Я тут расписал всё максимально жирно и по делу:

Как получить 4800 рублей с гарантией сразу после активации карты.
Как докрутить схему до 18-25к с помощью доп. бонусов.
И главное — КАК АБУЗИТЬ акции с 100% кэшбеком, чтобы банк реально платил тебе за покупки.

Никакой воды. Только схема.

👉 Лови статью, бро: https://clck.ru/3SYogg

Прочитай внимательно. 
Если после прочтения останутся вопросы — пиши в ЛС, решим. Погнали! 🚀"""

        keyboard = keyboard_builder.build_main_keyboard()
        
        logger.info(f"📤 Отправка приветствия пользователю {user_id}")
        bot.send_message(
            message.chat.id, 
            welcome_text, 
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        logger.info(f"✅ Приветствие успешно отправлено пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в start_command: {e}")


@bot.message_handler(commands=['reload'])
def reload_command(message):
    """Обработчик команды /reload (только для админа)"""
    user_id = message.from_user.id
    logger.info(f"🔄 Получена команда /reload от пользователя {user_id}")
    
    if user_id == ADMIN_ID:
        if repository.reload():
            bot.send_message(message.chat.id, "✅ Данные успешно обновлены!")
            logger.info(f"✅ Данные обновлены админом {user_id}")
        else:
            bot.send_message(message.chat.id, "❌ Ошибка при обновлении данных")
    else:
        logger.warning(f"⚠️ Неавторизованная попытка /reload от {user_id}")
        bot.send_message(message.chat.id, "⛔ У вас нет прав")


@bot.message_handler(commands=['help'])
def help_command(message):
    """Обработчик команды /help"""
    user_id = message.from_user.id
    logger.info(f"❓ Получена команда /help от {user_id}")
    
    help_text = (
        "📚 Доступные команды:\n\n"
        "/start - Начать работу с ботом\n"
        "/reload - Обновить данные из Excel (только для админа)\n"
        "/help - Показать это сообщение"
    )
    bot.send_message(message.chat.id, help_text)


@bot.message_handler(func=lambda message: True)
def default_message(message):
    """Обработчик всех остальных сообщений"""
    user_id = message.from_user.id
    logger.info(f"💬 Получено текстовое сообщение от {user_id}: {message.text[:50]}")
    bot.reply_to(message, "Используйте команду /start для начала работы")


# ==================== ОБРАБОТЧИКИ CALLBACK ====================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработчик callback запросов от кнопок"""
    user_id = call.from_user.id
    logger.info(f"🔘 Получен callback от {user_id}: {call.data}")
    
    callback_data = CallbackFactory.parse(call.data)
    callback_type = callback_data.get('type')

    try:
        if callback_type == CallbackFactory.MAIN_MENU:
            logger.info(f"🏠 Возврат в главное меню для {user_id}")
            keyboard = keyboard_builder.build_main_keyboard()
            bot.edit_message_text(
                "Выберите интересующую вас группу оферов:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=keyboard
            )
            bot.answer_callback_query(call.id)

        elif callback_type == CallbackFactory.CONTACT_ADMIN:
            logger.info(f"📞 Запрос контакта админа от {user_id}")
            bot.answer_callback_query(
                call.id,
                "Администратор: @" + ADMIN_CONTACT,
                show_alert=True
            )

        elif callback_type == CallbackFactory.GROUP_PREFIX:
            group_name = callback_data.get('group_name')
            logger.info(f"📂 Просмотр группы '{group_name}' пользователем {user_id}")
            group = repository.get_group(group_name)

            if group:
                keyboard = keyboard_builder.build_group_keyboard(group_name, 0)
                bot.edit_message_text(
                    f"📂 {group_name}\n\nВыберите интересующий вас офер:",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=keyboard
                )
                logger.info(f"✅ Показана группа '{group_name}' для {user_id}")
            else:
                logger.warning(f"⚠️ Группа '{group_name}' не найдена")
                bot.answer_callback_query(call.id, "Группа не найдена", show_alert=True)

        elif callback_type == CallbackFactory.PAGE_PREFIX:
            group_name = callback_data.get('group_name')
            page = int(callback_data.get('value', 0))
            logger.info(f"📄 Переход на страницу {page} группы '{group_name}' для {user_id}")
            group = repository.get_group(group_name)

            if group:
                keyboard = keyboard_builder.build_group_keyboard(group_name, page)
                bot.edit_message_text(
                    f"📂 {group_name}\n\nВыберите интересующий вас офер:",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=keyboard
                )
            bot.answer_callback_query(call.id)

        elif callback_type == CallbackFactory.OFFER_PREFIX:
            group_name = callback_data.get('group_name')
            index = int(callback_data.get('value', 0))
            logger.info(f"📋 Просмотр офера #{index} из группы '{group_name}' для {user_id}")
            group = repository.get_group(group_name)

            if not group:
                logger.warning(f"⚠️ Группа '{group_name}' не найдена")
                bot.answer_callback_query(call.id, "Группа не найдена", show_alert=True)
                return

            offer = group.get_offer(index)
            if not offer:
                logger.warning(f"⚠️ Офер #{index} не найден")
                bot.answer_callback_query(call.id, "Офер не найден", show_alert=True)
                return

            keyboard = keyboard_builder.build_offer_keyboard(group_name, offer)
            bot.edit_message_text(
                offer.to_display_text(),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=keyboard,
                parse_mode='HTML',
                disable_web_page_preview=False
            )
            logger.info(f"✅ Показан офер '{offer.name}' для {user_id}")
            bot.answer_callback_query(call.id)

    except Exception as e:
        logger.error(f"❌ Ошибка в callback: {e}", exc_info=True)
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка", show_alert=True)
        except:
            logger.error("❌ Не удалось отправить ответ об ошибке")


# ==================== FLASK WEBHOOK ====================
app = Flask(__name__)
logger.info("✅ Flask приложение создано")


@app.route('/webhook', methods=['POST'])
def webhook():
    """Эндпоинт для получения обновлений от Telegram"""
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            logger.info(f"📨 Получен webhook: {json_string[:200]}")
            update = telebot.types.Update.de_json(json_string)
            
            # Обрабатываем сообщения
            if update.message:
                logger.info(f"📝 Сообщение от {update.message.from_user.id}: {update.message.text}")
                bot.process_new_updates([update])
                
                # Дополнительно обрабатываем /start вручную
                if update.message.text == '/start':
                    logger.info("🔥 ВРУЧНУЮ вызываем start_command")
                    start_command(update.message)
            
            # Обрабатываем callback-запросы
            elif update.callback_query:
                logger.info(f"🔘 Callback от {update.callback_query.from_user.id}: {update.callback_query.data}")
                bot.process_new_updates([update])
                
                # Дополнительно обрабатываем callback вручную
                logger.info("🔘 ВРУЧНУЮ вызываем handle_callback")
                handle_callback(update.callback_query)
            
            return 'OK', 200
        except Exception as e:
            logger.error(f"❌ Ошибка в webhook: {e}", exc_info=True)
            return 'Error', 500
    return 'Unsupported media type', 415


@app.route('/')
def index():
    """Проверка, что бот работает"""
    return 'Bot is running!', 200


@app.route('/health')
def health():
    """Эндпоинт для проверки здоровья"""
    return 'OK', 200


# ==================== НАСТРОЙКА WEBHOOK ====================
def setup_webhook():
    """Установка webhook при запуске"""
    webhook_url = os.environ.get('RENDER_EXTERNAL_URL')
    
    if not webhook_url:
        logger.error("❌ RENDER_EXTERNAL_URL не найден!")
        return False

    webhook_url = f"{webhook_url}/webhook"
    logger.info(f"🌐 Установка webhook: {webhook_url}")

    try:
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook успешно установлен: {webhook_url}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка установки webhook: {e}")
        return False


# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    # Устанавливаем webhook
    setup_webhook()
    
    # Запускаем Flask сервер
    logger.info(f"🚀 Запуск Flask сервера на порту {port}")
    app.run(host='0.0.0.0', port=port)
