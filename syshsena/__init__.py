# Usa PyMySQL como controlador de MySQL para que el proyecto funcione
# sin necesidad de compilar mysqlclient (ideal en Windows con XAMPP).
import pymysql

pymysql.install_as_MySQLdb()
