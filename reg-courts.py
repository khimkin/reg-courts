import time
import logging
import urllib.parse
import requests
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from selenium.common import NoSuchElementException
from twocaptcha import TwoCaptcha
from selenium import webdriver
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver import Keys
from tc_key import tc_key

RETRIES = 5
IMG_NAME = 'img.png'
WAIT = 0.5

CASE = ['ДЕЛО']
PROGRESS = ['ДВИЖЕНИЕ ДЕЛА']
PARTIES = ['СТОРОНЫ ПО ДЕЛУ (ТРЕТЬИ ЛИЦА)', 'УЧАСТНИКИ', 'СТОРОНЫ']
ACTS = ['СУДЕБНЫЕ АКТЫ']
PERSONS = ['ЛИЦА']
ENFORCEMENT_ORDERS = ['ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ']
LOWER_COURT_TRIALS = ['РАССМОТРЕНИЕ В НИЖЕСТОЯЩЕМ СУДЕ']
HEARINGS = ['СЛУШАНИЯ']
APPEAL = ['ОБЖАЛОВАНИЕ ПРИГОВОРОВ ОПРЕДЕЛЕНИЙ (ПОСТ.)', 'ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)']
TAG_NAME = '__namess'
TAG_DATE1 = 'case__entry_date1d'
TAG_DATE2 = 'case__entry_date2d'
BTN_CHANGE = 'Изменить'

solver = TwoCaptcha(tc_key)

logging.basicConfig(filename='parser.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

app = Flask(__name__)


# Запуск сервера
@app.route("/")
def get_args():
    domain = 'https://' + request.args.get('subdomain') + '.sudrf.ru'
    case_type = request.args.get('case_type')
    name = request.args.get('name')
    date_from = request.args.get('date_from') if request.args.get('date_from') else ''
    date_to = request.args.get('date_to') if request.args.get('date_to') else ''

    if not (request.args.get('subdomain') and case_type and name and any(str(i) in case_type for i in range(8))):
        return jsonify({'error': 'Отсутствуют обязательные или переданы некорректные аргументы'})

    else:
        logging.info('Запуск парсера')
        try:
            search_url = api_link(domain, case_type, name, date_from, date_to)
            if is_captcha(search_url):
                logging.info('Найдена капча')
                case_links = selenium_case_links(search_url, name, case_type, date_from, date_to)
            else:
                logging.info('Капча не найдена')
                case_links = bs_case_links(search_url)
            result = parse_cases(case_links)
            logging.info('Парсинг завершен')
            return result
        except Exception as exc:
            logging.error(f'Ошибка: {exc}')
            exit()


# Формирование ссылки поиска дел
def api_link(subdomain, case_type, name, date_from, date_to):
    nm = urllib.parse.quote(name.encode(encoding='windows-1251'))

    match case_type:
        case '0':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=1540005&new=0&G1_PARTS__NAMESS={nm}&delo_table=g1_case&g1_case__ENTRY_DATE1D={date_from}&g1_case__ENTRY_DATE2D={date_to}"
        case '1':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=5&new=5&G2_PARTS__NAMESS={nm}&delo_table=g2_case&g2_case__ENTRY_DATE1D={date_from}&g2_case__ENTRY_DATE2D={date_to}"
        case '2':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=1540006&new=0&U1_DEFENDANT__NAMESS={nm}&delo_table=u1_case&u1_case__ENTRY_DATE1D={date_from}&u1_case__ENTRY_DATE2D={date_to}"
        case '3':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=4&new=4&U2_DEFENDANT__NAMESS={nm}&delo_table=u2_case&u2_case__ENTRY_DATE1D={date_from}&u2_case__ENTRY_DATE2D={date_to}"
        case '4':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=41&new=0&P1_PARTS__NAMESS={nm}&delo_table=p1_case&p1_case__ENTRY_DATE1D={date_from}&p1_case__ENTRY_DATE2D={date_to}"
        case '5':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=42&new=0&P2_PARTS__NAMESS={nm}&delo_table=p2_case&p2_case__ENTRY_DATE1D={date_from}&p2_case__ENTRY_DATE2D={date_to}"
        case '6':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=1500001&new=0&adm_parts__NAMESS={nm}&delo_table=adm_case&adm_case__ENTRY_DATE1D={date_from}&adm_case__ENTRY_DATE2D={date_to}"
        case '7':
            url = f"{subdomain}/modules.php?name=sud_delo&srv_num=1&name_op=r&delo_id=1502001&new=0&adm1_parts__NAMESS={nm}&delo_table=adm1_case&adm1_case__ENTRY_DATE1D={date_from}&adm1_case__ENTRY_DATE2D={date_to}"
        case _:
            url = ''

    return url


# Получение объекта BeautifulSoup для ссылки
def get_soup(link):
    headers = {
        'user-agent': UserAgent().random
    }
    response = requests.get(url=link, headers=headers)
    response.encoding = 'windows-1251'
    return BeautifulSoup(response.text, 'html.parser')


# Получение ссылок на дела со страницы поиска
def get_links(soup, domain):
    if not (link_cells := soup.select("td[title^='Для получения справки по делу'] > a:first-child")):
        link_cells = soup.select("tbody tr > td:first-child > a[href^='/modules.php']")
    links = [domain + cell['href'] for cell in link_cells]

    return links


# Получение ссылок на дела по со всех страниц поиска через Selenium
def selenium_case_links(url, name, case_type, date_from, date_to):
    link = url.split('?')[0] + '?name=sud_delo&name_op=sf&delo_id=1540005'
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument(f"--user-agent={UserAgent().random}")

    with webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                          options=chrome_options) as browser:
        browser.implicitly_wait(10)
        browser.get(link)
        time.sleep(2)

        try:
            browser.find_element(By.XPATH, f"//a[contains(text(), '{BTN_CHANGE}')]").click()
            time.sleep(1)

            match case_type:
                case '0':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Гражданское судопроизводство')]/"
                                                   "ancestor::tr/following-sibling::tr[1]/td/div").click()

                case '1':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Гражданское судопроизводство')]/"
                                                   "ancestor::tr/following-sibling::tr[2]/td/div").click()

                case '2':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Уголовное судопроизводство')]/"
                                                   "ancestor::tr/following-sibling::tr[1]/td/div").click()

                case '3':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Уголовное судопроизводство')]/"
                                                   "ancestor::tr/following-sibling::tr[2]/td/div").click()

                case '4':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Административное судопроизводство')]/"
                                                   "ancestor::tr/following-sibling::tr[1]/td/div").click()

                case '5':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Административное судопроизводство')]/"
                                                   "ancestor::tr/following-sibling::tr[2]/td/div").click()

                case '6':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Дела об административных правонарушениях')]/"
                                                   "ancestor::tr/following-sibling::tr[1]/td/div").click()

                case '7':
                    browser.find_element(By.XPATH, "//div/strong[contains(text(), 'Дела об административных правонарушениях')]/"
                                                   "ancestor::tr/following-sibling::tr[2]/td/div").click()

            time.sleep(3)

        except NoSuchElementException:
            sel = browser.find_element(By.XPATH, "//select[@id='process-type']")
            sel.click()
            time.sleep(3)
            match case_type:
                case '0': browser.find_element\
                    (By.XPATH, "//optgroup[@label='Гражданское судопроизводство']/option[1]").click()
                case '1': browser.find_element\
                    (By.XPATH, "//optgroup[@label='Гражданское судопроизводство']/option[2]").click()
                case '2': browser.find_element \
                    (By.XPATH, "//optgroup[@label='Уголовное судопроизводство']/option[1]").click()
                case '3': browser.find_element \
                    (By.XPATH, "//optgroup[@label='Уголовное судопроизводство']/option[2]").click()
                case '4': browser.find_element \
                    (By.XPATH, "//optgroup[@label='Административное судопроизводство']/option[1]").click()
                case '5': browser.find_element \
                    (By.XPATH, "//optgroup[@label='Административное судопроизводство']/option[2]").click()
                case '6': browser.find_element \
                    (By.XPATH, "//optgroup[@label='Дела об административных правонарушениях']/option[1]").click()
                case '7': browser.find_element \
                    (By.XPATH, "//optgroup[@label='Дела об административных правонарушениях']/option[2]").click()

            time.sleep(3)

        browser.find_element(By.XPATH, "//img[starts-with(@src, 'data: image/png;base64,')]").screenshot(IMG_NAME)
        tag = browser.find_element(By.XPATH, "//input[@id='captcha']")
        tag.send_keys(solver.normal(IMG_NAME)['code'])

        logging.info('Капча решена')

        time.sleep(3)

        browser.find_element(By.XPATH, f"//input[contains(translate(@name, "
                                       f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                                       f"'{TAG_DATE1.lower()}')][last()]").send_keys(date_from)
        time.sleep(1)

        browser.find_element(By.XPATH, f"//input[contains(translate(@name, "
                                       f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                                       f"'{TAG_DATE2.lower()}')][last()]").send_keys(date_to)
        time.sleep(1)

        tag = browser.find_element(By.XPATH, f"//input[contains(translate(@name, "
                                       f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                                       f"'{TAG_NAME.lower()}')][last()]")
        tag.send_keys(name)
        time.sleep(1)
        tag.send_keys(Keys.ENTER)
        time.sleep(3)
        logging.info('Данные введены в форму поиска')
        res_link = browser.current_url

    soup = get_soup(res_link)
    cases_count = 0

    try:
        tag = get_text(soup.find('td', align='right'))
        cases_count = tag.split('—')[1].split('.')[0].strip()
        pages = 1 + (int(cases_count) - 1) // 25
    except:
        tag = get_text(soup.find('div', class_='lawcase-count').find('b'))
        cases_count = tag.strip()
        pages = 1 + (int(cases_count) - 1) // 20
    finally:
        logging.info(f'Надено дел: {cases_count}')

    domain = url.split('/modules')[0]

    case_links = get_links(soup, domain)
    if pages > 1:
        url = browser.current_url.replace('name_op=r&', 'name_op=r&page=1&_page=1&')
        for page in range(2, pages + 1):
            time.sleep(3)
            url = url.replace(f'name_op=r&page={page - 1}&_page={page - 1}&', f'name_op=r&page={page}&_page={page}&')
            browser.get(url)
            time.sleep(2)
            soup = BeautifulSoup(browser.page_source, 'lxml')
            case_links += get_links(soup, domain)

    time.sleep(2)

    return case_links


# Получение ссылок на дела по со всех страниц поиска через BeautifulSoup
def bs_case_links(url):
    soup = get_soup(url)
    domain = url.split('/modules')[0]
    if tag := soup.find('td', align="right"):
        cases_count = tag.text.split('—')[1].split('.')[0].strip()
    else:
        cases_count = 0

    logging.info(f'Найдено дел: {cases_count}')
    pages = 1 + (int(cases_count) - 1) // 25
    case_links = get_links(soup, domain)

    if pages > 1:
        for page in range(2, pages + 1):
            time.sleep(WAIT)
            soup = get_soup(f'{url}&page={page}')
            case_links += get_links(soup, domain)

    return case_links

# Получение текста тега
def get_text(tag):
    no_br = str(tag).replace('<br/>', ';')
    return BeautifulSoup(no_br, 'lxml').text.strip() if tag else ''

# Получение элемента карточки дела по названию поля
def find_next(soup, text):
    cell = soup.find('b', string=text)
    return get_text(cell.find_next('td')) if cell else ''


# Получение данных из вкладки карточки дела
def get_table(soup, title):
    table = ''
    if tag := soup.find('th', string=lambda x: x and x.strip().upper() in title):
        table = tag.find_parent('table')
    else:
        if tag := soup.find('li', id=lambda x: x and x.startswith('tab_id'),
                                    string=lambda y: y and y.strip().upper() in title):
            tab_id = tag['id']
            table = soup.find('div', id=lambda x: x and x.endswith(tab_id.rsplit('_', 1)[-1])
                                and x.startswith('tab_content')).find('table')

    return table


# Парсинг карточки дела
def parse_cases(case_links):

    data = {'cases': []}
    for case_link in case_links[:]:
        time.sleep(WAIT)
        soup = get_soup(case_link)
        logging.info(f'Парсим дело: {case_link}')


        table = get_table(soup, CASE)

        offset = 2 if get_text(table.select_one('tr:first-of-type th:first-of-type')) in CASE else 1

        case = {'case_details': {
            'case_num': get_text(soup.find('div', class_=lambda x: x and (x == 'casenumber' or x == 'case-num'))),
            'case_id': find_next(table, 'Уникальный идентификатор дела'),
            'receipt_date': find_next(table, 'Дата поступления'),
            'category': find_next(table, 'Категория дела'),
            'judge': find_next(table, 'Судья'),
            'trial_date': find_next(table, 'Дата рассмотрения'),
            'trial_result': find_next(table, 'Результат рассмотрения'),
            'trial_mark': find_next(table, 'Признак рассмотрения дела')}}

        if table := get_table(soup, PROGRESS):
            case['case_progress'] = []
            for row in table('tr')[offset:]:
                event = {
                    'event_name': get_text(row('td')[0]),
                    'event_date': get_text(row('td')[1]),
                    'event_time': get_text(row('td')[2]),
                    'event_place': get_text(row('td')[3]),
                    'event_result': get_text(row('td')[4]),
                    'event_ground': get_text(row('td')[5]),
                    'event_mark': get_text(row('td')[6]),
                    'issue_date': get_text(row('td')[7])}
                case['case_progress'].append(event)

        if table := get_table(soup, PERSONS):
            case['persons'] = []
            for row in table('tr')[offset:]:
                event = {
                    'person_name': get_text(row('td')[0]),
                    'article_list': get_text(row('td')[1]),
                    'trial_date': get_text(row('td')[2]),
                    'trial_result': get_text(row('td')[3])}
                case['persons'].append(event)

        if table := get_table(soup, LOWER_COURT_TRIALS):
            case['lower_court_trials'] = {
                'case_number': find_next(table, 'Номер дела в первой инстанции'),
                'peace_justice': find_next(table, 'Судья (мировой судья) первой инстанции')
            }

        if table := get_table(soup, PARTIES):
            case['case_parties'] = []
            for row in table('tr')[offset:]:
                party = {
                    'party_type': get_text(row('td')[0]),
                    'party_name': get_text(row('td')[1]),
                    'party_inn': get_text(row('td')[2]),
                    'party_kpp': get_text(row('td')[3]),
                    'party_ogrn': get_text(row('td')[4]),
                    'party_ogrnip': get_text(row('td')[5])}
                case['case_parties'].append(party)

        if table := get_table(soup, HEARINGS):
            case['hearings'] = []
            for row in table('tr')[offset:]:
                hearing = {
                    'hearing_date': get_text(row('td')[0]),
                    'hearing_time': get_text(row('td')[1]),
                    'hearing_place': get_text(row('td')[2]),
                    'hearing_mark': get_text(row('td')[3]),
                    'issue_date': get_text(row('td')[4])}
                case['hearings'].append(hearing)


        if table := get_table(soup, ENFORCEMENT_ORDERS):
            case['enforcement_orders'] = []
            for row in table('tr')[offset:]:
                order = {
                    'issue_date': get_text(row('td')[2-offset]),
                    'serial_number': get_text(row('td')[3-offset]),
                    'e-order_number': get_text(row('td')[4-offset]),
                    'status': get_text(row('td')[5-offset]),
                    'recipient': get_text(row('td')[6-offset])}
                case['enforcement_orders'].append(order)

        if table := get_table(soup, APPEAL):
            case['appeal'] = {
                'receipt_date': find_next(table, 'Дата поступления'),
                'appeal_type': find_next(table, 'Вид жалобы (представления)'),
                'appellant': find_next(table, 'Заявитель'),
                'appeal_decision_date': find_next(table, 'Дата решения по поступившей жалобе'),
                'appeal_decision': find_next(table, 'Решение по поступившей жалобе'),
                'higher_court': find_next(table, 'Вышестоящий суд'),
                'transfer_to_higher_court_date': find_next(table, 'Дата направления дела в вышест. суд'),
                'higher_court_assignment_date': find_next(table, 'Назначено в вышестоящий суд на дату'),
                'higher_court_trial_date': find_next(table, 'Дата рассмотрения жалобы'),
                'appeal_result': find_next(table, 'Результат обжалования'),
                'return_to_lower_court_date': find_next(table, 'Дата возврата в нижестоящий суд')
            }
        tabs = soup.find('ul', class_=lambda x: x and (x == 'tabs' or x == 'bookmarks'))
        if tab := tabs.find('li', string=lambda x: x.strip().upper() in ACTS):
            i = tabs('li').index(tab)
            case['acts'] = [get_text(x) for x in soup.find(
                'div', id=lambda x: x and (x == f'cont{i+1}' or x == 'tab_content_Document'))('li')]
        else:
            case['acts'] = []

        case['url'] = case_link
        data['cases'].append(case)

    return data

# Проверка, есть ли на странице поиска дел капча
def is_captcha(url):
    link = url.split('?')[0] + '?name=sud_delo&name_op=sf&delo_id=1540005'
    if 'Проверочный код' in get_soup(link).text:
        return True
    else:
        return False


if __name__ == '__main__':
    app.run(debug=True)