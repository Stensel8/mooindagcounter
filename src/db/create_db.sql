-- Mooindag!
CREATE TABLE IF NOT EXISTS counts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    client_ip TEXT NOT NULL
);

-- Mooindag... rechten geven.
GRANT ALL PRIVILEGES ON mooindagcounter.* TO 'mooindagcounter'@'%';
FLUSH PRIVILEGES;
