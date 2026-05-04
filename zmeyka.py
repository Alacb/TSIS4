import pygame
import random
import psycopg2
import json
import os
from pygame.locals import *

# --- КОНФИГУРАЦИЯ БАЗЫ ---
DB_CONFIG = {"dbname": "postgres", "user": "postgres", "password": "", "host": "localhost"}
SCREEN_WIDTH, SCREEN_HEIGHT = 1200, 750
GRID_SIZE = 30

# Цвета
WHITE, BLACK, RED, GREEN = (255, 255, 255), (10, 10, 10), (255, 0, 0), (0, 255, 0)
DARK_RED, YELLOW, BLUE, GRAY = (139, 0, 0), (255, 255, 0), (0, 0, 255), (100, 100, 100)

class SnakeGame:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Consolas", 24)
        self.big_font = pygame.font.SysFont("Consolas", 50)
        
        self.state = "MENU"
        self.username = ""
        self.best_score = 0 # Заменили PB на Best Score
        self.load_settings()
        self.reset_game()

    def load_settings(self):
        self.sets_file = "settings.json"
        try:
            if os.path.exists(self.sets_file):
                with open(self.sets_file, "r") as f:
                    self.settings = json.load(f)
            else: raise FileNotFoundError
        except:
            self.settings = {"snake_color": [0, 255, 0], "grid": True, "sound": True}
            self.save_settings()

    def save_settings(self):
        with open(self.sets_file, "w") as f:
            json.dump(self.settings, f)

    def db_get_best(self):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("SELECT MAX(score) FROM game_sessions gs JOIN players p ON gs.player_id = p.id WHERE p.username = %s", (self.username,))
            res = cur.fetchone()[0]
            conn.close()
            return res if res else 0
        except: return 0

    def db_save(self):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("INSERT INTO players (username) VALUES (%s) ON CONFLICT (username) DO NOTHING", (self.username,))
            cur.execute("SELECT id FROM players WHERE username = %s", (self.username,))
            p_id = cur.fetchone()[0]
            cur.execute("INSERT INTO game_sessions (player_id, score, level_reached) VALUES (%s, %s, %s)", 
                        (p_id, self.score, self.level))
            conn.commit()
            conn.close()
        except: pass

    def db_get_top10(self):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("SELECT p.username, gs.score, gs.level_reached, gs.played_at::date FROM game_sessions gs JOIN players p ON gs.player_id = p.id ORDER BY gs.score DESC LIMIT 10")
            data = cur.fetchall()
            conn.close()
            return data
        except: return []

    def reset_game(self):
        self.score, self.level = 0, 1
        self.head = [300, 300]
        self.body = [[270, 300], [240, 300]]
        self.dir = (1, 0)
        self.food, self.poison = None, None
        self.powerup = None
        self.obstacles = []
        self.active_powerup = None
        self.shield_active = False
        self.spawn_stuff()

    def spawn_stuff(self):
        occ = set(tuple(p) for p in self.body) | set(self.obstacles)
        def get_free_pos():
            while True:
                p = (random.randint(1, 38)*30, random.randint(1, 23)*30)
                if p not in occ: return p

        self.food = get_free_pos()
        self.poison = get_free_pos() if random.random() < 0.4 else None
        if not self.powerup and random.random() < 0.2:
            # Синий - щит, Желтый - скорость
            self.powerup = {'pos': get_free_pos(), 'type': random.choice(['Speed+', 'Slow', 'Shield']), 'spawn_time': pygame.time.get_ticks()}
        if self.level >= 3:
            self.obstacles = [get_free_pos() for _ in range(self.level * 2)]

    def update(self):
        now = pygame.time.get_ticks()
        speed_mod = 1.0
        
        if self.active_powerup:
            if now > self.active_powerup['end_time']: self.active_powerup = None
            elif self.active_powerup['type'] == 'Speed+': speed_mod = 1.5
            elif self.active_powerup['type'] == 'Slow': speed_mod = 0.6

        if self.powerup and now - self.powerup['spawn_time'] > 8000: self.powerup = None

        new_head = [self.head[0] + self.dir[0]*30, self.head[1] + self.dir[1]*30]
        h_t = tuple(new_head)

        hit_wall = new_head[0] < 0 or new_head[0] >= SCREEN_WIDTH or new_head[1] < 0 or new_head[1] >= SCREEN_HEIGHT
        if hit_wall or h_t in self.obstacles or new_head in self.body:
            if self.shield_active: 
                self.shield_active = False
                # Отскакиваем или просто не двигаемся, чтобы не умереть мгновенно снова
                return 1.0 
            else:
                self.db_save()
                self.state = "GAMEOVER"
                return 1.0

        self.body.insert(0, list(self.head))
        self.head = new_head

        if h_t == self.food:
            self.score += 1
            if self.score % 5 == 0: self.level += 1
            self.spawn_stuff()
        elif self.poison and h_t == self.poison:
            for _ in range(2): 
                if len(self.body) > 1: self.body.pop()
                else: 
                    self.state = "GAMEOVER"
                    self.db_save()
            self.poison = None
        elif self.powerup and h_t == self.powerup['pos']:
            if self.powerup['type'] == 'Shield': self.shield_active = True
            else: self.active_powerup = {'type': self.powerup['type'], 'end_time': now + 5000}
            self.powerup = None
        else:
            self.body.pop()
            
        return speed_mod

    def draw_text(self, text, font, color, x, y, center=False):
        surf = font.render(text, True, color)
        rect = surf.get_rect(center=(x,y)) if center else surf.get_rect(topleft=(x,y))
        self.screen.blit(surf, rect)

    def run(self):
        while True:
            self.screen.fill(BLACK)
            for event in pygame.event.get():
                if event.type == QUIT: return
                if event.type == KEYDOWN:
                    if self.state == "MENU":
                        if event.key == K_RETURN and self.username: 
                            self.best_score = self.db_get_best()
                            self.state = "PLAYING"
                        elif event.key == K_l: self.state = "LEADERBOARD"
                        elif event.key == K_s: self.state = "SETTINGS"
                        elif event.key == K_BACKSPACE: self.username = self.username[:-1]
                        elif event.unicode.isalnum(): self.username += event.unicode
                    elif self.state == "PLAYING":
                        if event.key == K_UP and self.dir != (0, 1): self.dir = (0, -1)
                        if event.key == K_DOWN and self.dir != (0, -1): self.dir = (0, 1)
                        if event.key == K_LEFT and self.dir != (1, 0): self.dir = (-1, 0)
                        if event.key == K_RIGHT and self.dir != (-1, 0): self.dir = (1, 0)
                    elif self.state in ["GAMEOVER", "LEADERBOARD", "SETTINGS"]:
                        if event.key == K_m: self.state = "MENU"
                        if event.key == K_r and self.state == "GAMEOVER": 
                            self.reset_game()
                            self.state = "PLAYING"
                        if self.state == "SETTINGS":
                            if event.key == K_g: self.settings["grid"] = not self.settings["grid"]
                            if event.key == K_v: self.settings["sound"] = not self.settings["sound"]
                            if event.key == K_c: self.settings["snake_color"] = [random.randint(50,255) for _ in range(3)]
                            self.save_settings()

            if self.state == "MENU":
                self.draw_text("SNAKE DATABASE", self.big_font, GREEN, 600, 150, True)
                self.draw_text(f"USER: {self.username}_", self.font, WHITE, 600, 300, True)
                self.draw_text("[ENTER] Play  [L] Leaderboard  [S] Settings", self.font, GRAY, 600, 500, True)

            elif self.state == "SETTINGS":
                self.draw_text("SETTINGS", self.big_font, BLUE, 600, 100, True)
                self.draw_text(f"[G] Grid: {'ON' if self.settings['grid'] else 'OFF'}", self.font, WHITE, 400, 250)
                self.draw_text(f"[V] Sound: {'ON' if self.settings['sound'] else 'OFF'}", self.font, WHITE, 400, 300)
                self.draw_text(f"[C] Change Color", self.font, WHITE, 400, 350)
                pygame.draw.rect(self.screen, self.settings["snake_color"], (650, 350, 30, 30))
                self.draw_text("Press [M] to Back", self.font, GREEN, 600, 600, True)

            elif self.state == "PLAYING":
                s_mod = self.update()
                if self.settings["grid"]:
                    for x in range(0, SCREEN_WIDTH, 30): pygame.draw.line(self.screen, (25,25,25), (x,0), (x,SCREEN_HEIGHT))
                
                pygame.draw.rect(self.screen, RED, (*self.food, 30, 30))
                if self.poison: pygame.draw.rect(self.screen, DARK_RED, (*self.poison, 30, 30))
                for o in self.obstacles: pygame.draw.rect(self.screen, GRAY, (*o, 30, 30))
                
                if self.powerup:
                    p_c = BLUE if self.powerup['type'] == 'Shield' else YELLOW
                    pygame.draw.circle(self.screen, p_c, (self.powerup['pos'][0]+15, self.powerup['pos'][1]+15), 12)
                
                for p in self.body: pygame.draw.rect(self.screen, self.settings["snake_color"], (*p, 30, 30))
                # Голова меняет цвет, если есть щит
                h_color = WHITE if self.shield_active else YELLOW
                pygame.draw.rect(self.screen, h_color, (*self.head, 30, 30))
                
                # Текст счета
                curr_best = max(self.score, self.best_score)
                self.draw_text(f"SCORE: {self.score} | LVL: {self.level} | BEST: {curr_best}", self.font, WHITE, 20, 20)
                self.clock.tick(10 * s_mod + self.level)

            elif self.state == "LEADERBOARD":
                self.draw_text("TOP 10", self.big_font, YELLOW, 600, 80, True)
                top = self.db_get_top10()
                for i, (u, s, l, d) in enumerate(top):
                    self.draw_text(f"{i+1}. {u:<10} Score: {s:<5} Lvl: {l} {d}", self.font, WHITE, 350, 180 + i*40)
                self.draw_text("Press [M] to Back", self.font, GREEN, 600, 680, True)

            elif self.state == "GAMEOVER":
                self.draw_text("GAME OVER", self.big_font, RED, 600, 200, True)
                self.draw_text(f"SCORE: {self.score} | BEST: {max(self.score, self.best_score)}", self.font, WHITE, 600, 350, True)
                self.draw_text("[R] Retry  [M] Menu", self.font, GREEN, 600, 500, True)

            pygame.display.flip()

if __name__ == "__main__":
    SnakeGame().run()