import os
import logging
import re
import time
import sqlite3
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService

# Configuración de logs
def configurar_logs():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Eliminación de la base de datos si existe
def eliminar_bd(nombre_bd):
    if os.path.exists(nombre_bd):
        os.remove(nombre_bd)
        logging.info("Base de datos eliminada.")

# Inicialización de la base de datos SQLite
def init_db(nombre_bd):
    conn = sqlite3.connect(nombre_bd)
    with conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS mensajes (id TEXT PRIMARY KEY, nombre TEXT, numero TEXT)''')
    return conn

def cargar_estado(conn):
    with conn:
        cursor = conn.execute('SELECT id FROM mensajes')
        mensajes_enviados = {row[0] for row in cursor.fetchall()}
    return {"mensajes_enviados": mensajes_enviados}

def guardar_estado(conn, mensaje_id, nombre_cliente, numero_encontrado):
    try:
        with conn:
            conn.execute('INSERT INTO mensajes (id, nombre, numero) VALUES (?, ?, ?)', (mensaje_id, nombre_cliente, numero_encontrado))
    except sqlite3.IntegrityError:
        logging.warning(f"El mensaje con id {mensaje_id} ya está en la base de datos. Saltando inserción.")

def generar_respuesta_predeterminada(nombre_cliente):
    return f"Hola {nombre_cliente}, si te gustaría recibir propuestas de financiamiento o ver fotos de nuestros autos usados disponibles, déjanos tu número de teléfono y nos pondremos en contacto lo antes posible. ¡Gracias por considerarnos!"

def iniciar_sesion(driver):
    driver.get('https://www.facebook.com')
    input("Inicia sesión en Facebook y presiona Enter para continuar...")
    WebDriverWait(driver, 300).until(EC.url_contains("facebook.com"))

def detectar_y_responder_mensaje_nuevo(driver, estado, conn):
    while True:
        try:
            mensaje_nuevo = get_new_message_element(driver)
            if mensaje_nuevo:
                procesar_mensaje(driver, mensaje_nuevo, estado, conn)
            time.sleep(10)  # Esperar antes de volver a escanear
        except Exception as e:
            logging.error(f"Error durante la ejecución: {e}")
            time.sleep(5)

def procesar_mensaje(driver, mensaje_element, estado, conn):
    try:
        mensaje_href = mensaje_element.get_attribute('href')
        if "/messages/t/" not in mensaje_href:
            return

        mensaje_id = mensaje_href.split('/')[-2]

        if mensaje_id in estado["mensajes_enviados"]:
            return

        logging.info(f"Accediendo al mensaje nuevo con href: {mensaje_href}")
        mensaje_element.click()
        time.sleep(5)  # Esperar 5 segundos para asegurar que los mensajes se carguen completamente
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, '//div[@role="presentation"]//div[@dir="auto"]')))

        nombre_cliente = obtener_nombre_cliente(driver)
        if not nombre_cliente:
            nombre_cliente = "Cliente"
        logging.info(f"Nombre del cliente: {nombre_cliente}")

        mensajes = obtener_todos_los_mensajes(driver)
        numero_encontrado = buscar_numero_mensaje(mensajes)

        # Cambiar la ubicación del archivo a la ruta especificada
        file_path = "C:\\Users\\manza\\Desktop\\botmark\\mensajes.txt"
        
        if numero_encontrado:
            with open(file_path, "a", encoding="utf-8") as file:
                file.write(f"ID: {mensaje_id}, Nombre: {nombre_cliente}, Número: {numero_encontrado}\n")
            logging.info(f"Número encontrado y guardado: {numero_encontrado}")
            guardar_estado(conn, mensaje_id, nombre_cliente, numero_encontrado)
        else:
            if not mensaje_predeterminado_enviado(mensajes):
                respuesta = generar_respuesta_predeterminada(nombre_cliente)
                enviar_respuesta(driver, respuesta)
                logging.info("Mensaje predeterminado enviado.")
                guardar_estado(conn, mensaje_id, nombre_cliente, None)
                
                # Esperar 2 minutos para posibles respuestas del cliente
                time.sleep(300)
                
                # Re-verificar los mensajes después de enviar el mensaje predeterminado
                mensajes = obtener_todos_los_mensajes(driver)
                numero_encontrado = buscar_numero_mensaje(mensajes)
                
                if numero_encontrado:
                    with open(file_path, "a", encoding="utf-8") as file:
                        file.write(f"ID: {mensaje_id}, Nombre: {nombre_cliente}, Número: {numero_encontrado}\n")
                    logging.info(f"Número encontrado y guardado: {numero_encontrado}")
                    guardar_estado(conn, mensaje_id, nombre_cliente, numero_encontrado)
        
        estado["mensajes_enviados"].add(mensaje_id)
    except StaleElementReferenceException as e:
        logging.error(f"Error de referencia obsoleta al procesar mensaje {mensaje_href}: {e}")
    except Exception as e:
        logging.error(f"Error al procesar mensaje: {e}")

def obtener_nombre_cliente(driver, retries=3):
    for attempt in range(retries):
        try:
            nombre_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//img[contains(@alt, " ")]'))
            )
            return nombre_element.get_attribute("alt")
        except StaleElementReferenceException:
            if attempt < retries - 1:
                logging.info("Reintentando obtener el nombre del cliente debido a un error de referencia obsoleta.")
                time.sleep(1)
            else:
                logging.error("No se pudo obtener el nombre del cliente después de varios intentos.")
        except Exception as e:
            logging.error(f"No se pudo obtener el nombre del cliente: {e}")
            break
    return None

def obtener_todos_los_mensajes(driver, retries=3):
    for attempt in range(retries):
        try:
            mensajes_elements = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, '//div[@role="presentation"]//div[@dir="auto"]'))
            )
            return [mensaje_element.text for mensaje_element in mensajes_elements]
        except StaleElementReferenceException:
            if attempt < retries - 1:
                logging.info("Reintentando obtener mensajes debido a un error de referencia obsoleta.")
                time.sleep(1)
            else:
                logging.error("No se pudieron obtener los mensajes después de varios intentos.")
        except Exception as e:
            logging.error(f"No se pudieron obtener los mensajes: {e}")
            break
    return []

def buscar_numero_mensaje(mensajes):
    for mensaje in mensajes:
        try:
            # Eliminar caracteres no numéricos
            numeros = re.sub(r'\D', '', mensaje)
            if len(numeros) == 10:
                return numeros
        except Exception as e:
            logging.error(f"Error al buscar número en el mensaje: {e}")
    return None

def mensaje_predeterminado_enviado(mensajes):
    try:
        for mensaje in mensajes:
            if "si te gustaría recibir propuestas de financiamiento" in mensaje:
                return True
    except:
        pass
    return False

def enviar_respuesta(driver, respuesta):
    try:
        campo_texto = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//div[@aria-label="Mensaje"]'))
        )
        campo_texto.click()
        campo_texto.send_keys(respuesta)
        campo_texto.send_keys(Keys.RETURN)
        logging.info("Respuesta enviada exitosamente.")
    except Exception as e:
        logging.error(f"Error al enviar respuesta: {e}")

def iniciar_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-notifications")
    return webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

def manejar_error_critico(driver=None):
    logging.critical("Ocurrió un error crítico. Reiniciando el script...")
    if driver:
        driver.quit()
    time.sleep(5)
    main()

def get_new_message_element(driver):
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    for a in soup.find_all('a', href=True):
        if '/messages/t/' in a['href']:
            parent_div = a.find_parent('div', {'class': 'x78zum5 xdt5ytf'})
            if parent_div:
                time_elements = parent_div.find_all('span', {'class': 'x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x x4zkp8e x3x7a5m x1nxh6w3 x1sibtaa xo1l8bm xi81zsa'})
                for time_element in time_elements:
                    time_text = time_element.get_text()
                    if "min" in time_text or "seg" in time_text:
                        time_number = int(re.search(r'\d+', time_text).group())
                        if ("min" in time_text and time_number <= 10) or ("seg" in time_text and time_number <= 600):
                            return driver.find_element(By.XPATH, f'//a[@href="{a["href"]}"]')
    return None

def main():
    configurar_logs()
    eliminar_bd('estado_mensajes.db')
    conn = init_db('estado_mensajes.db')
    estado = cargar_estado(conn)
    driver = iniciar_driver()
    try:
        iniciar_sesion(driver)
        driver.get('https://www.facebook.com/messages/t/')
        detectar_y_responder_mensaje_nuevo(driver, estado, conn)
    except Exception as e:
        logging.error(f"Error principal: {e}")
        manejar_error_critico(driver)
    finally:
        if 'driver' in locals():
            driver.quit()

if __name__ == "__main__":
    main()
