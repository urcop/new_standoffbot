import datetime

from aiogram import Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.types import InputFile
from sqlalchemy.orm import sessionmaker

from tg_bot.keyboards.inline.output_items import returns_output_button, returns_output_callback
from tg_bot.keyboards.reply import main_menu, back_to_main
from tg_bot.keyboards.reply.admin import admin_keyboard
from tg_bot.models.case import Case, CaseItems
from tg_bot.models.history import GoldHistory, BalanceHistory, CaseHistory
from tg_bot.models.items import OutputQueue, Item
from tg_bot.models.jackpot import JackpotGame, JackpotBets
from tg_bot.models.logs import Logs
from tg_bot.models.lottery import TicketGames
from tg_bot.models.product import Product
from tg_bot.models.promocode import Promocode
from tg_bot.models.seasons import Season, Season2User
from tg_bot.models.support import Tickets
from tg_bot.models.tower import TowerGames
from tg_bot.models.users import User, Referral
from tg_bot.models.workers import Worker, Support, WorkerHistory
from tg_bot.services.broadcast import broadcast
from tg_bot.states.product import AddProduct


async def broadcaster(message: types.Message):
    session_maker = message.bot['db']
    if message.content_type == 'photo':
        text = message.caption[4:]
        photo_id = message.photo[-1].file_id
    else:
        text = message.text[4:]
        photo_id = None
    users = [i[0] for i in await User.get_all_users(session_maker=session_maker)]
    await broadcast(bot=message.bot, users=users, text=text, disable_notifications=True,
                    message_type=message.content_type, photo_id=photo_id)


async def user_information(message: types.Message):
    session_maker = message.bot['db']
    text = message.text.split(' ')
    user_id = int(text[1])
    reg_date = await User.get_reg_date(user_id=user_id, session_maker=session_maker)
    user_balance = await User.get_balance(session_maker=session_maker, telegram_id=user_id)
    user_gold = await User.get_gold(session_maker=session_maker, telegram_id=user_id)
    count_purchases = await GoldHistory.get_sum_user_purchase(session_maker=session_maker,
                                                              telegram_id=user_id)
    seasons_id = await Season.get_all_seasons(session_maker=session_maker)
    user = User(telegram_id=user_id)
    count_refs = await User.count_referrals(session_maker=session_maker, user=user)
    count_outputs = await OutputQueue.get_user_requests(user_id=user_id, session_maker=session_maker)
    user_prefixes = [
        f'{season[0]}: {await Season2User.get_user_prefix(session_maker=session_maker, telegram_id=user_id, season_id=int(season[0]))}'
        for season in seasons_id]
    user_prefixes_text = ' '.join(user_prefixes)
    text = [
        f'📂 Дата регистрации: {reg_date}',
        f'🔑 ID: {user_id}',
        f'💸 Баланс: {user_balance} руб.',
        f'💰 Золото: {user_gold}',
        f'⏰ Запросов на вывод золота: {count_outputs}',
        f'💵 Куплено золота: {count_purchases} за все время',
        f'🎁 Префиксы: {user_prefixes_text}',
        f'👥 Количество приглашенных пользователей: {count_refs if count_refs else 0}'
    ]
    await message.answer('\n'.join(text))


async def generate_currency_text(type: str, notify_text: dict, session_maker: sessionmaker, count_currency: int,
                                 user_id: int):
    date = datetime.datetime.now()
    text = 'золота' if type == 'gold' else 'рублей'
    if count_currency > 0:
        await User.add_currency(session_maker=session_maker, telegram_id=user_id, currency_type=type,
                                value=count_currency)

        if type == 'gold':
            await GoldHistory.add_gold_purchase(session_maker=session_maker, telegram_id=user_id, gold=count_currency,
                                                date=date)
            await Logs.add_log(telegram_id=user_id,
                               message=f'Пополнил золото на {count_currency}',
                               time=date.strftime('%H.%M'),
                               date=date.strftime('%d.%m.%Y'),
                               session_maker=session_maker)
        else:
            await BalanceHistory.add_balance_purchase(session_maker=session_maker, telegram_id=user_id,
                                                      money=count_currency, date=date)
            await Logs.add_log(telegram_id=user_id,
                               message=f'Пополнил баланс на {count_currency}',
                               time=date.strftime('%H.%M'),
                               date=date.strftime('%d.%m.%Y'),
                               session_maker=session_maker)

        notify_text['user_notify'] = f'На ваш счет зачислено {count_currency} {text}'
        notify_text['admin_confirm'] = f'На аккаунт пользователя {user_id} переведено {count_currency} {text}'
    elif count_currency < 0:
        count_currency = count_currency * -1
        await User.take_currency(session_maker=session_maker, telegram_id=user_id, currency_type=type,
                                 value=count_currency)
        if type == 'balance':
            await BalanceHistory.add_balance_purchase(session_maker, user_id, count_currency * -1, date=date)
            await Logs.add_log(telegram_id=user_id,
                               message=f'Забрали баланса {count_currency}р',
                               time=date.strftime('%H.%M'),
                               date=date.strftime('%d.%m.%Y'),
                               session_maker=session_maker)

        notify_text['user_notify'] = f'С вашего счета снято {count_currency} {text}'
        notify_text['admin_confirm'] = f'Счет пользователя {user_id} снято {count_currency} {text}'
    return notify_text


async def give_currency(message: types.Message):
    session_maker = message.bot['db']
    text = message.text.split(' ')
    notify_text = {
        'admin_confirm': '',
        'user_notify': ''
    }

    user_id = int(text[1])
    count_currency = int(text[2])

    result = {}
    if text[0][1:] == 'givem':
        result = await generate_currency_text('balance', notify_text=notify_text, session_maker=session_maker,
                                              count_currency=count_currency, user_id=user_id)
    elif text[0][1:] == 'giveg':
        result = await generate_currency_text('gold', notify_text=notify_text, session_maker=session_maker,
                                              count_currency=count_currency, user_id=user_id)
    await message.answer(result['admin_confirm'])
    await message.bot.send_message(user_id, result['user_notify'])


async def add_promo(message: types.Message):
    session_maker = message.bot['db']
    text = message.text.split(' ')
    name = text[1]
    promo_type = text[2]
    value = int(text[3])
    count_use = int(text[4])

    if promo_type == 'g':
        promo_type = 'gold'
    elif promo_type == 'm':
        promo_type = 'balance'

    await Promocode.create_promo(session_maker=session_maker, code_name=name, currency=promo_type, count_use=count_use,
                                 value=value)
    await message.answer(f'Промокод <b>{name}</b> на <b>{count_use}</b> использований успешно добавлен!')


async def tell(message: types.Message):
    text = message.text.split(' ') if message.content_type == 'text' else message.caption.split(' ')
    text.pop(0)
    user_id = int(text[0])
    text.pop(0)
    message_to_user = ' '.join(text)
    if message.content_type == 'text':
        await message.bot.send_message(user_id, text=f'<b>Администратор отправил вам сообщение:</b> {message_to_user}')
    elif message.content_type == 'photo':
        await message.copy_to(user_id, caption=f'<b>Администратор отправил вам сообщение:</b> {message_to_user}')


async def stat(message: types.Message):
    session_maker = message.bot['db']
    date = message.text.split(' ')
    try:
        second_date = date[2]
    except IndexError:
        second_date = None
    if not second_date:
        success_outputs = await WorkerHistory.get_stats_period(session_maker=session_maker, date=date[1])
        gold = await GoldHistory.get_stats_params(session_maker, date[1])
        money = await BalanceHistory.get_stats_params(session_maker, date[1])
        reg_users = await User.get_users_by_reg_date(date[1], session_maker)
        reg_users_id = await User.get_users_id_by_reg_date(date[1], session_maker)
        reg_ref_users = [user[0] for user in reg_users_id if await Referral.get_user(session_maker, user[0])]
        warns = await Tickets.get_tickets_by_date(date[1], session_maker)
        text = [
            f'Статистика за {"все время" if date[1] == "all" else date[1]}',
            f'Пополнено денег: {money}',
            f'Продано золота: {gold}',
            f'Зарегистрировано пользователей: {reg_users}',
            f'Зарегистрировано по реферальной ссылке: {len(reg_ref_users)}',
            f'Сами нашли бота: {reg_users - len(reg_ref_users)}',
            f'Обращений в поддержку: {warns}',
            f'Успешных выводов золота: {success_outputs}'
        ]
        await message.answer('\n'.join(text))
    else:
        gold = 0
        money = 0
        reg_users = 0
        warns = 0
        success_outputs = 0
        reg_users_id = []
        datetime_second_date = datetime.datetime.strptime(second_date, '%d.%m.%Y')
        period = datetime.datetime.strptime(second_date, '%d.%m.%Y') - datetime.datetime.strptime(date[1], '%d.%m.%Y')
        for i in range(period.days):
            day = (datetime_second_date - datetime.timedelta(days=i)).strftime('%d.%m.%Y')
            reg_users_id.extend(await User.get_users_id_by_reg_date(day, session_maker))
            gold_day = await GoldHistory.get_stats_params(session_maker, day)
            gold += gold_day if gold_day else 0
            money_day = await BalanceHistory.get_stats_params(session_maker, day)
            money += money_day if money_day else 0
            reg_users_day = await User.get_users_by_reg_date(day, session_maker)
            reg_users += reg_users_day if reg_users_day else 0
            warns_day = await Tickets.get_tickets_by_date(day, session_maker)
            warns += warns_day if warns_day else 0
            success_outputs_day = await WorkerHistory.get_stats_period(session_maker=session_maker, date=day)
            success_outputs += success_outputs_day if success_outputs_day else 0

    reg_ref_users = [user[0] for user in reg_users_id if await Referral.get_user(session_maker, user[0])]
    text = [
        f'Статистика с {date[1]} по {date[2]}',
        f'Пополнено денег: {money}',
        f'Продано золота: {gold}',
        f'Зарегистрировано пользователей: {reg_users}',
        f'Зарегистрировано по реферальной ссылке: {len(reg_ref_users)}',
        f'Сами нашли бота: {reg_users - len(reg_ref_users)}',
        f'Обращений в поддержку: {warns}',
        f'Успешных выводов золота: {success_outputs}'
    ]
    await message.answer('\n'.join(text))


async def cinfo(message: types.Message):
    session_maker = message.bot['db']
    date = message.text.split(' ')
    try:
        second_date = date[2]
    except IndexError:
        second_date = None
    if not second_date:
        money_spent = await CaseHistory.get_case_stats_money(session_maker=session_maker, date=date[1])
        gold_won = await CaseHistory.get_case_stats_gold(session_maker=session_maker, date=date[1])
        opened = await CaseHistory.get_case_stats_opened(session_maker=session_maker, date=date[1])
        text = [
            f'Статистика за {"все время" if date[1] == "all" else date[1]}',
            f'Открыто кейсов: {opened}',
            f'Потрачено денег: {money_spent}',
            f'Выиграно золота: {gold_won}'
        ]
        await message.answer('\n'.join(text))
    else:
        money_spent = 0
        gold_won = 0
        opened = 0
        datetime_second_date = datetime.datetime.strptime(second_date, '%d.%m.%Y')
        period = datetime.datetime.strptime(second_date, '%d.%m.%Y') - datetime.datetime.strptime(date[1], '%d.%m.%Y')
        for i in range(period.days):
            day = (datetime_second_date - datetime.timedelta(days=i)).strftime('%d.%m.%Y')
            money_spent_day = await CaseHistory.get_case_stats_money(session_maker=session_maker, date=day)
            money_spent += money_spent_day if money_spent_day else 0
            gold_won_day = await CaseHistory.get_case_stats_gold(session_maker=session_maker, date=day)
            gold_won += gold_won_day if gold_won_day else 0
            opened_day = await CaseHistory.get_case_stats_opened(session_maker=session_maker, date=day)
            opened += opened_day if opened_day else 0
        text = [
            f'Статистика с {date[1]} по {date[2]}',
            f'Открыто кейсов: {opened}',
            f'Потрачено денег: {money_spent}',
            f'Выиграно золота: {gold_won}'
        ]
        await message.answer('\n'.join(text))


async def add_worker(message: types.Message):
    session_maker = message.bot['db']
    text = message.text.split(' ')
    await User.set_role(user_id=int(text[1]), role='worker', session_maker=session_maker)
    await Worker.add_worker(user_id=int(text[1]), password=text[2], session_maker=session_maker)
    await message.answer('Работник добавлен!')
    await message.bot.send_message(chat_id=int(text[1]), text='Вас назначили работником')


async def delete_worker(message: types.Message):
    session_maker = message.bot['db']
    text = message.text.split(' ')
    await User.set_role(user_id=int(text[1]), role='user', session_maker=session_maker)
    await Worker.delete_worker(user_id=int(text[1]), session_maker=session_maker)
    await message.answer('Работник удален!')
    await message.bot.send_message(chat_id=int(text[1]), text='Вас сняли с должности работника')


async def add_support(message: types.Message):
    session_maker = message.bot['db']
    dp: Dispatcher = message.bot['dp']
    text = message.text.split(' ')
    await User.set_role(user_id=int(text[1]), role='support', session_maker=session_maker)
    await Support.add_support(user_id=int(text[1]), password=text[2], session_maker=session_maker)
    await message.answer('Работник добавлен!')
    user_state = dp.current_state(chat=int(text[1]), user=int(text[1]))
    await user_state.finish()
    await message.bot.send_message(chat_id=int(text[1]), text='Вас назначили работником тех поддержки',
                                   reply_markup=main_menu.keyboard)


async def delete_support(message: types.Message):
    session_maker = message.bot['db']
    dp: Dispatcher = message.bot['dp']
    text = message.text.split(' ')
    await User.set_role(user_id=int(text[1]), role='user', session_maker=session_maker)
    await Support.delete_support(user_id=int(text[1]), session_maker=session_maker)
    await message.answer('Работник тех. поддержки удален!')
    user_state = dp.current_state(chat=int(text[1]), user=int(text[1]))
    await user_state.finish()
    await message.bot.send_message(chat_id=int(text[1]), text='Вас сняли с должности работника тех. поддержки',
                                   reply_markup=main_menu.keyboard)


async def admin_menu(message: types.Message, state: FSMContext):
    await message.answer('Меню администратора', reply_markup=admin_keyboard)
    await state.set_state('admin_in_job')


async def output(message: types.Message):
    session_maker = message.bot['db']
    config = message.bot['config']
    if await OutputQueue.is_active(worker_id=message.from_user.id, session_maker=session_maker):
        await message.answer('Вы не завершили предыдущий вывод!')
        return
    first_free_ticket = await OutputQueue.get_first_free_queue(session_maker)
    if first_free_ticket is None:
        await message.answer('Нет активных запросов')
        return
    first_free_ticket_split = str(first_free_ticket[0]).split(':')
    id = int(first_free_ticket_split[0])
    user = int(first_free_ticket_split[1])
    gold = float(first_free_ticket_split[2])
    photo = first_free_ticket_split[3]
    item_id = int(first_free_ticket_split[4])
    user_nickname = first_free_ticket_split[5]

    item_name = await Item.get_item_name(id=item_id, session_maker=session_maker)
    photo_file = InputFile(config.misc.base_dir / 'uploads' / 'outputs' / photo)

    await OutputQueue.set_worker(worker_id=message.from_user.id, id=id, session_maker=session_maker)

    admins = await User.get_admins(session_maker)
    for admin in admins:
        await message.bot.send_message(chat_id=admin[0],
                                       text=f'{message.from_user.id} взял запрос пользователя {user}')

    text = [
        f'🔑ID: <code>{user}</code>',
        f'🔫Предмет: {item_name}',
        f'💵Цена предмета: {gold}',
        f'🔗Ссылка для связи https://t.me/{user_nickname}'
    ]
    await message.answer_photo(photo=photo_file, caption='\n'.join(text),
                               reply_markup=await returns_output_button(user_id=user,
                                                                        gold=int(gold),
                                                                        ticket_id=id))


async def finish(message: types.Message):
    session_maker = message.bot['db']
    admins = await User.get_admins(session_maker)
    taken_ticket = await OutputQueue.taken_ticket(worker_id=message.from_user.id, session_maker=session_maker)
    date = datetime.datetime.now()
    if taken_ticket is None:
        await message.answer('У вас нет активных запросов')
        return
    taken_ticket_split = str((taken_ticket)[0]).split(':')
    id = int(taken_ticket_split[0])
    user = int(taken_ticket_split[1])
    gold = float(taken_ticket_split[2])
    free_tickets = len(await OutputQueue.get_all_free_queue(session_maker=session_maker))
    await OutputQueue.delete_from_queue(id=id, session_maker=session_maker)

    for admin in admins:
        await message.bot.send_message(chat_id=admin[0],
                                       text=f'{message.from_user.id} завершил запрос пользователя {user}')
    await message.answer('Проверка закончена!\n'
                         f'Впереди еще {free_tickets}\n'
                         'Нажмите /output')

    await Logs.add_log(telegram_id=user,
                       message=f'Завершен вывод средств',
                       time=date.strftime('%H.%M'),
                       date=date.strftime('%d.%m.%Y'),
                       session_maker=session_maker)
    await WorkerHistory.add_worker_history(worker_id=message.from_user.id, gold=int(gold) * 0.8,
                                           session_maker=session_maker, date=date)
    await message.bot.send_message(chat_id=user, text='🎉 Запрос на вывод золота, успешно завершён!')
    referrer = await Referral.get_referrer(telegram_id=user, session_maker=session_maker)
    if referrer:
        date = datetime.datetime.now()
        await message.bot.send_message(chat_id=referrer, text='Вы получили 5G за реферала')
        await User.add_currency(telegram_id=referrer, currency_type='gold', value=5, session_maker=session_maker)
        await GoldHistory.add_gold_purchase(telegram_id=referrer, gold=5, session_maker=session_maker, date=date)


async def returns_output(call: types.CallbackQuery, callback_data: dict):
    session_maker = call.bot['db']
    user = int(callback_data.get('user_id'))
    gold = int(callback_data.get('gold')) * 0.8
    date = datetime.datetime.now()
    id = int(callback_data.get('ticket_id'))
    await OutputQueue.delete_from_queue(id=id, session_maker=session_maker)
    admins = await User.get_admins(session_maker)
    for admin in admins:
        await call.bot.send_message(chat_id=admin[0],
                                    text=f'{call.from_user.id} выполнил возврат запроса пользователя {user}')
    await call.message.delete()
    await User.add_currency(session_maker, user, currency_type='gold', value=gold)
    await call.message.answer('Средства возвращены на баланс пользователя')
    await Logs.add_log(telegram_id=user,
                       message=f'Совершен возврат средств',
                       time=date.strftime('%H.%M'),
                       date=date.strftime('%d.%m.%Y'),
                       session_maker=session_maker)
    await call.bot.send_message(chat_id=user, text='Средства вернулись обратно на ваш баланс')


async def worker_stats(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    worker_id = int(params[1])
    date = params[2]
    try:
        second_date = params[3]
    except IndexError:
        second_date = None
    if not second_date:
        gold_issued = await WorkerHistory.get_worker_stats(worker_id=worker_id, date=date, session_maker=session_maker)
        text = [
            f'Статистика работника за {"все время" if date == "all" else date}',
            f'Выведено {gold_issued} золота'
        ]
        await message.answer('\n'.join(text))
    else:
        gold_issued = 0
        datetime_second_date = datetime.datetime.strptime(second_date, '%d.%m.%Y')
        period = datetime.datetime.strptime(second_date, '%d.%m.%Y') - datetime.datetime.strptime(date, '%d.%m.%Y')
        for i in range(period.days):
            day = (datetime_second_date - datetime.timedelta(days=i)).strftime('%d.%m.%Y')
            gold_issued_day = await WorkerHistory.get_worker_stats(worker_id=worker_id, date=day,
                                                                   session_maker=session_maker)
            gold_issued += gold_issued_day if gold_issued_day else 0
        text = [
            f'Статистика работника c {date} по {second_date}',
            f'Выведено {gold_issued} золота'
        ]
        await message.answer('\n'.join(text))


async def ticket_stats(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    date = params[1]
    try:
        second_date = params[2]
    except IndexError:
        second_date = None
    if not second_date:
        games = await TicketGames.get_count_games_period(date=date, session_maker=session_maker)
        sum_bets = await TicketGames.get_sum_bets_period(date=date, session_maker=session_maker)
        win = await TicketGames.get_sum_win_period(date=date, session_maker=session_maker)
        text = [
            f'Статистика лотереи за {"все время" if date == "all" else date}',
            f'Количество игр: {games}',
            f'Сумма: {sum_bets}',
            f'Выигрыш: {win}',
        ]
        await message.answer('\n'.join(text))
    else:
        games = 0
        sum_bets = 0
        win = 0
        datetime_second_date = datetime.datetime.strptime(second_date, '%d.%m.%Y')
        period = datetime.datetime.strptime(second_date, '%d.%m.%Y') - datetime.datetime.strptime(date, '%d.%m.%Y')
        for i in range(period.days):
            day = (datetime_second_date - datetime.timedelta(days=i)).strftime('%d.%m.%Y')
            games_in_day = await TicketGames.get_count_games_period(date=day, session_maker=session_maker)
            games += games_in_day if games_in_day else 0
            sum_bets_day = await TicketGames.get_sum_bets_period(date=day, session_maker=session_maker)
            sum_bets += sum_bets_day if sum_bets_day else 0
            win_day = await TicketGames.get_sum_win_period(date=day, session_maker=session_maker)
            win += win_day if win_day else 0
        text = [
            f'Статистика лотереи с {date} по {second_date}',
            f'Количество игр: {games}',
            f'Сумма: {sum_bets}',
            f'Выигрыш: {win}',
        ]
        await message.answer('\n'.join(text))


async def tower_stats(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    date = params[1]
    try:
        second_date = params[2]
    except IndexError:
        second_date = None
    if not second_date:
        games = await TowerGames.get_count_games_period(date=date, session_maker=session_maker)
        sum_bets = await TowerGames.get_sum_bets_period(date=date, session_maker=session_maker)
        win = await TowerGames.get_sum_win_period(date=date, session_maker=session_maker)
        text = [
            f'Статистика башни за {"все время" if date == "all" else date}',
            f'Количество игр: {games}',
            f'Сумма: {sum_bets}',
            f'Выигрыш: {win}',
        ]
        await message.answer('\n'.join(text))
    else:
        games = 0
        sum_bets = 0
        win = 0
        datetime_second_date = datetime.datetime.strptime(second_date, '%d.%m.%Y')
        period = datetime.datetime.strptime(second_date, '%d.%m.%Y') - datetime.datetime.strptime(date, '%d.%m.%Y')
        for i in range(period.days):
            day = (datetime_second_date - datetime.timedelta(days=i)).strftime('%d.%m.%Y')
            games_day = await TowerGames.get_count_games_period(date=day, session_maker=session_maker)
            games += games_day if games_day else 0
            sum_bets_day = await TowerGames.get_sum_bets_period(date=day, session_maker=session_maker)
            sum_bets += sum_bets_day if sum_bets_day else 0
            win_day = await TowerGames.get_sum_win_period(date=day, session_maker=session_maker)
            win += win_day if win_day else 0
        text = [
            f'Статистика башни с {date} по {second_date}',
            f'Количество игр: {games}',
            f'Сумма: {sum_bets}',
            f'Выигрыш: {win}',
        ]
        await message.answer('\n'.join(text))


async def add_case(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    params.pop(0)
    price = int(params[0])
    params.pop(0)
    name = ' '.join(params)
    await Case.add_case(name=name, price=price, session_maker=session_maker)
    await message.answer(f'Кейс {name} успешно добавлен.')
    await message.answer(f'CASE ID: <code>{await Case.get_case_id(name=name, session_maker=session_maker)}</code>')


async def delete_case(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    name = params[1]
    await Case.delete_case(name=name, session_maker=session_maker)
    await message.answer(f'Кейс {name} удален')


async def change_case_visible(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    case_id = int(params[1])
    visible = bool(int(params[2]))
    case_name = await Case.get_case_name(id=case_id, session_maker=session_maker)

    await Case.change_visible(case_id=case_id, visible=visible, session_maker=session_maker)
    text = {
        False: f'Кейс {case_name} скрыт из списка',
        True: f'Кейс {case_name} добавлен в список'
    }
    await message.answer(text[visible])


async def add_case_item(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    case_id = int(params[1])
    price = int(params[2])
    chance = int(params[3])
    params.pop(3)
    params.pop(2)
    params.pop(1)
    params.pop(0)
    item_name = ' '.join(params)

    await CaseItems.add_case_item(case_id=case_id, game_price=price, chance=chance, item_name=item_name,
                                  session_maker=session_maker)
    await message.answer(f'Предмет {item_name} успешно добавлен.')


async def delete_case_item(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    params.pop(0)
    item_name = ' '.join(params)

    await CaseItems.delete_case_item(item_name=item_name, session_maker=session_maker)
    await message.answer(f'Предмет {item_name} удален')


async def delete_item(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    params.pop(0)
    category = int(params[0])
    params.pop(0)
    name = ' '.join(params)

    await Item.delete_item(category=category, name=name, session_maker=session_maker)
    await message.answer('Предмет успешно удален')


async def add_item(message: types.Message, state: FSMContext):
    params = message.text.split(' ')
    type_item = int(params[1])
    category_item = int(params[2])
    quality_item = int(params[3])

    type_item_text = {
        1: 'Оружие',
        2: 'Наклейка',
        3: 'Брелок'
    }
    category_item_text = {
        0: 'Без категории',
        1: 'Regular',
        2: 'StatTrack'
    }
    quality_item_text = {
        1: 'Arcane',
        2: 'Legendary',
        3: 'Epic',
        4: 'Rare',
    }
    text = f"""
Характеристики предмета:
Тип: {type_item_text[type_item]}
Категория: {category_item_text[category_item]}
Качество: {quality_item_text[quality_item]}
"""
    data = {
        'type': type_item,
        'category': category_item,
        'quality': quality_item,
    }
    await message.answer(text)
    await message.answer('Укажите название предмета')
    await state.set_state('add_item_name')
    await state.update_data(data=data)


async def add_item_name(message: types.Message, state: FSMContext):
    session_maker = message.bot['db']
    data = await state.get_data('add_item_name')
    name = message.text
    await Item.add_item(name=name, type=data['type'], category=data['category'], quality=data['quality'],
                        session_maker=session_maker)
    await message.answer('Предмет успешно добавлен')
    await state.finish()


async def delete_product(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    params.pop(0)
    name = ' '.join(params)
    id = await Product.get_id(name=name, session_maker=session_maker)
    await Product.delete_product(id=int(id), session_maker=session_maker)
    await message.answer('Товар удален!')


async def add_product(message: types.Message):
    await message.answer('Укажите название товара', reply_markup=back_to_main.keyboard)
    await AddProduct.name.set()


async def add_product_name(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['name'] = message.text
        await message.answer('Укажите описание товара')
        await AddProduct.description.set()


async def add_product_description(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['description'] = message.text
        await message.answer('Укажите цену товара')
        await AddProduct.price.set()


async def add_product_price(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['price'] = int(message.text)
        await message.answer('Укажите количество товара либо -1 чтобы сделать его бесконечным')
        await AddProduct.count.set()


async def add_product_count(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['count'] = message.text
        await message.answer('Отправьте фото товара')
        await AddProduct.photo.set()


async def add_product_photo(message: types.Message, state: FSMContext):
    session_maker = message.bot['db']
    config = message.bot['config']
    date = datetime.datetime.now()
    async with state.proxy() as data:
        await Product.add_product(data['name'], data['description'], price=int(data['price']),
                                  session_maker=session_maker, date=date, count=int(data['count']))
        product_id = await Product.get_id(name=data['name'], session_maker=session_maker)
        photo_name = f'{product_id}.jpg'
        await message.photo[-1].download(
            destination_file=config.misc.base_dir / 'uploads' / 'aprods' / photo_name)
        await Product.add_photo(id=product_id, photo=photo_name, session_maker=session_maker)
        await message.answer('Товар успешно добавлен', reply_markup=main_menu.keyboard)
        await state.finish()


async def support_stats(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    support_id = int(params[1])
    date = params[2]
    try:
        second_date = params[3]
    except IndexError:
        second_date = None
    if not second_date:
        done = await Tickets.get_done_support_tickets(support_id=support_id, date=date, session_maker=session_maker)
        canceled = await Tickets.get_cancel_support_tickets(support_id=support_id, date=date,
                                                            session_maker=session_maker)

        await message.answer(f"За {date} работник {support_id}\n"
                             f"Ответил на {done} тикетов\n"
                             f"Отклонил {canceled} тикетов")
    else:
        done = 0
        canceled = 0
        datetime_second_date = datetime.datetime.strptime(second_date, '%d.%m.%Y')
        period = datetime.datetime.strptime(second_date, '%d.%m.%Y') - datetime.datetime.strptime(date, '%d.%m.%Y')
        for i in range(period.days):
            day = (datetime_second_date - datetime.timedelta(days=i)).strftime('%d.%m.%Y')
            done_day = await Tickets.get_done_support_tickets(support_id=support_id, date=day,
                                                              session_maker=session_maker)
            done += done_day if done_day else 0
            canceled_day = await Tickets.get_cancel_support_tickets(support_id=support_id, date=day,
                                                                    session_maker=session_maker)
            canceled += canceled_day if canceled_day else 0
        await message.answer(f"За период с {date} по {second_date} работник\n"
                             f"Ответил на {done} тикетов\n"
                             f"Отклонил {canceled} тикетов")


async def ref_stats(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    user_id = int(params[1])
    user = User(telegram_id=user_id)
    count_refs = await user.count_referrals(session_maker, user)
    referrals = [ref[0] for ref in await Referral.get_referrals(user_id, session_maker)]
    referrals_gold = [await GoldHistory.get_sum_user_purchase(session_maker, referral) for referral in referrals if
                      await GoldHistory.get_sum_user_purchase(session_maker, referral)]

    text = [
        f'👥 Количество приглашенных пользователей: {count_refs if count_refs else 0}',
        f'Куплено золота рефералами: {sum(referrals_gold)}'
    ]

    await message.answer('\n'.join(text))


async def jackpot_stats(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    date = params[1]
    ids = [id[0] for id in await JackpotGame.get_all_room_ids_period(date, session_maker)]
    all_bets = [await JackpotBets.get_sum_bets(id, session_maker) for id in ids]
    if len(all_bets) < 1:
        await message.answer('За этот период игр не найдено')
        return
    text = [
        f'Количество игр: {len(ids)}',
        f'Банк: {sum(all_bets)}',
        f'Максимальный банк: {max(all_bets)}'
    ]
    await message.answer('\n'.join(text))


async def logs(message: types.Message):
    session_maker = message.bot['db']
    params = message.text.split(' ')
    telegram_id = int(params[1])
    date = params[2]
    logs = await Logs.get_user_logs(telegram_id=telegram_id, date=date, session_maker=session_maker)
    if len(logs) == 0:
        await message.answer(f'У пользователя {telegram_id} за {date} нет логов')
        return
    text = [f'Логи {telegram_id} за {date}']
    for log in logs:
        log_time = log[0]
        log_message = log[1]
        text.append(f'{log_time} {log_message}')

    await message.answer('\n'.join(text))


def register_admin_handlers(dp: Dispatcher):
    dp.register_message_handler(broadcaster, text_startswith='/ads', content_types=['text', 'photo'], is_admin=True)
    dp.register_message_handler(user_information, Command(['info']), is_admin=True)
    dp.register_message_handler(give_currency, Command(['giveg', 'givem']), is_admin=True)
    dp.register_message_handler(add_promo, Command(['promo']), is_admin=True)
    dp.register_message_handler(add_worker, Command(['ajob']), is_admin=True)
    dp.register_message_handler(add_support, Command(['arep']), is_admin=True)
    dp.register_message_handler(delete_support, Command(['drep']), is_admin=True)
    dp.register_message_handler(delete_worker, Command(['djob']), is_admin=True)
    dp.register_message_handler(stat, Command(['stat']), is_admin=True)
    dp.register_message_handler(cinfo, Command(['cinfo']), is_admin=True)
    dp.register_message_handler(worker_stats, Command(['ijob']), is_admin=True)
    dp.register_message_handler(ticket_stats, Command(['ticket']), is_admin=True)
    dp.register_message_handler(tower_stats, Command(['ginfo']), is_admin=True)
    dp.register_message_handler(add_case, Command(['addcase']), is_admin=True)
    dp.register_message_handler(delete_case, Command(['dcase']), is_admin=True)
    dp.register_message_handler(add_case_item, Command(['addcaseitem']), is_admin=True)
    dp.register_message_handler(delete_case_item, Command(['dcaseitem']), is_admin=True)
    dp.register_message_handler(change_case_visible, Command(['casevisible']), is_admin=True)
    dp.register_message_handler(delete_item, Command(['ditem']), is_admin=True)
    dp.register_message_handler(add_item, Command(['aitem']), is_admin=True)
    dp.register_message_handler(add_item_name, state='add_item_name', is_admin=True)
    dp.register_message_handler(delete_product, Command(['dprod']), is_admin=True)
    dp.register_message_handler(add_product, Command(['addproduct']), is_admin=True)
    dp.register_message_handler(support_stats, Command(['rep']), is_admin=True)
    dp.register_message_handler(ref_stats, Command(['ref']), is_admin=True)
    dp.register_message_handler(jackpot_stats, Command(['jpinfo']), is_admin=True)
    dp.register_message_handler(add_product_name, state=AddProduct.name, is_admin=True)
    dp.register_message_handler(add_product_description, state=AddProduct.description, is_admin=True)
    dp.register_message_handler(add_product_price, state=AddProduct.price, is_admin=True)
    dp.register_message_handler(add_product_count, state=AddProduct.count, is_admin=True)
    dp.register_message_handler(add_product_photo, state=AddProduct.photo, content_types=['photo'], is_admin=True)

    dp.register_message_handler(admin_menu, Command(['admin']), is_admin=True)
    dp.register_message_handler(output, Command(['output']), state='admin_in_job', is_admin=True)
    dp.register_message_handler(finish, Command(['finish']), state='admin_in_job', is_admin=True)

    dp.register_message_handler(tell, text_startswith='/tell', content_types=['text', 'photo'], is_admin=True)

    dp.register_callback_query_handler(returns_output, returns_output_callback.filter(), state='admin_in_job',
                                       is_admin=True)

    dp.register_message_handler(logs, Command(['logs']), is_admin=True)
