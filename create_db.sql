CREATE DATABASE IF NOT EXISTS mooindagcounter;

USE mooindagcounter;

CREATE TABLE IF NOT EXISTS counts (
    id INT PRIMARY KEY,
    message VARCHAR(500) NOT NULL,
    date VARCHAR(200) NOT NULL,
    time VARCHAR(200) NOT NULL,
    client_ip VARCHAR(15) NOT NULL
);

CREATE USER IF NOT EXISTS 'mooindagcounter'@'localhost' IDENTIFIED BY '';
GRANT ALL PRIVILEGES ON mooindagcounter.* TO 'mooindagcounter'@'localhost';

