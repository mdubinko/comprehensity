import http from 'http';

export function createServer() {
    return http.createServer((_req, res) => res.end('ok'));
}
