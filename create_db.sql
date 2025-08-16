CREATE DATABASE IF NOT EXISTS mooindagcounter;

USE mooindagcounter;

CREATE TABLE IF NOT EXISTS counts (
    id INT PRIMARY KEY,
    message VARCHAR(500) NOT NULL,
    date VARCHAR(200) NOT NULL,
    time VARCHAR(200) NOT NULL,
    client_ip VARCHAR(15) NOT NULL
);

CREATE USER IF NOT EXISTS 'mooindagcounter'@'%' IDENTIFIED BY 'M4vQYn8Tu2bcugU*4!H6^dgcb54zX*dFe8Y9$Njp9t^xPemXTw4!4iEx**UoEGx^9ufNLyTSA#5kcbtG';
GRANT ALL PRIVILEGES ON mooindagcounter.* TO 'mooindagcounter'@'%';