import logging
import pytest
import uuid
from pygame.math import Vector2
import pygame
import random
import numpy as np
import cv2
import time

from .base_render import BaseRender
from gobigger.utils import FOOD_COLOR, THORNS_COLOR, SPORE_COLOR, PLAYER_COLORS, BACKGROUND, BLACK, WHITE
from gobigger.utils import FOOD_COLOR_GRAYSCALE, THORNS_COLOR_GRAYSCALE, SPORE_COLOR_GRAYSCALE, PLAYER_COLORS_GRAYSCALE, BACKGROUND_GRAYSCALE
from gobigger.utils import to_aliased_circle


class EnvRender(BaseRender):
    '''
    Overview:
        No need to use a new window, giving a global view and the view that each player can see
    '''
    def __init__(self, width, height, padding=(0,0), cell_size=10, 
                 scale_up_ratio=1.5, vision_x_min=100, vision_y_min=100, only_render=True, use_spatial=True):
        super(EnvRender, self).__init__(width, height, padding=padding, 
                                        cell_size=cell_size, only_render=only_render)
        self.scale_up_ratio = scale_up_ratio
        self.vision_x_min = vision_x_min
        self.vision_y_min = vision_y_min
        self.use_spatial = use_spatial

    def fill_all(self, screen, food_balls, thorns_balls, spore_balls, players):
        font = pygame.font.SysFont('Menlo', 12, True)
        # render all balls
        for ball in food_balls:
            pygame.draw.circle(screen, FOOD_COLOR_GRAYSCALE, ball.position, ball.radius)
        for ball in thorns_balls:
            pygame.draw.polygon(screen, THORNS_COLOR_GRAYSCALE, to_aliased_circle(ball.position, ball.radius))
        for ball in spore_balls:
            pygame.draw.circle(screen, SPORE_COLOR_GRAYSCALE, ball.position, ball.radius)
        for index, player in enumerate(players):
            for ball in player.get_balls():
                pygame.draw.circle(screen, PLAYER_COLORS_GRAYSCALE[int(ball.owner)], ball.position, ball.radius)
        screen_data = pygame.surfarray.array2d(screen)
        return screen_data

    def get_clip_screen(self, screen_data, rectangle):
        if len(screen_data.shape) == 3:
            screen_data_clip = screen_data[rectangle[0]:rectangle[2], 
                                           rectangle[1]:rectangle[3], :]
        elif len(screen_data.shape) == 2:
            screen_data_clip = screen_data[rectangle[0]:rectangle[2], 
                                           rectangle[1]:rectangle[3]]
        else:
            raise NotImplementedError
        return screen_data_clip

    def get_rectangle_by_player(self, player):
        '''
        Multiples of the circumscribed matrix of the centroid
        '''
        centroid = player.cal_centroid()
        xs_max = 0
        ys_max = 0
        for ball in player.get_balls():
            direction_center = centroid - ball.position
            if abs(direction_center.x) + ball.radius > xs_max:
                xs_max = abs(direction_center.x) + ball.radius
            if abs(direction_center.y) + ball.radius > ys_max:
                ys_max = abs(direction_center.y) + ball.radius
        xs_max = max(xs_max, self.vision_x_min)
        ys_max = max(ys_max, self.vision_y_min)
        scale_up_len =  max(xs_max, ys_max)
        left_top_x = min(max(int(centroid.x - scale_up_len * self.scale_up_ratio), 0), 
                         max(int(self.width_full - scale_up_len * self.scale_up_ratio * 2), 0))
        left_top_y = min(max(int(centroid.y - scale_up_len * self.scale_up_ratio), 0),
                         max(int(self.height_full - scale_up_len * self.scale_up_ratio * 2), 0))
        right_bottom_x = min(int(left_top_x + scale_up_len * self.scale_up_ratio * 2), self.width_full)
        right_bottom_y = min(int(left_top_y + scale_up_len * self.scale_up_ratio * 2), self.height_full)
        rectangle = (left_top_x, left_top_y, right_bottom_x, right_bottom_y)
        return rectangle

    def get_overlap(self, rectangle, food_balls, thorns_balls, spore_balls, player):
        def food_generator(rectangle, food_balls):
            for ball in food_balls:
                if ball.judge_in_rectangle(rectangle):
                    yield({'position': tuple(ball.position), 'radius': ball.radius})

        def thorns_generator(rectangle, thorns_balls):
            for ball in thorns_balls:
                if ball.judge_in_rectangle(rectangle):
                    yield({'position': tuple(ball.position), 'radius': ball.radius})

        def spore_generator(rectangle, spore_balls):
            for ball in spore_balls:
                if ball.judge_in_rectangle(rectangle):
                    yield({'position': tuple(ball.position), 'radius': ball.radius})
        
        def player_generator(rectangle, player):
            for ball in player.get_balls():
                if ball.judge_in_rectangle(rectangle):
                    yield({'position': tuple(ball.position), 'radius': ball.radius, 
                                        'player': player.name, 'team': player.team_name})

        return  {'food': food_generator(rectangle, food_balls), 'thorns': thorns_generator(rectangle, thorns_balls), 
                'spore': spore_generator(rectangle, spore_balls), 'clone': player_generator(rectangle, player)}

    def update_all(self, food_balls, thorns_balls, spore_balls, players):
        screen_data_all = None
        feature_layers = None
        if self.use_spatial:
            screen_all = pygame.Surface((self.width, self.height), depth=8)
            screen_all.fill(BACKGROUND_GRAYSCALE)
            screen_data_all = self.fill_all(screen_all, food_balls, thorns_balls, spore_balls, players)
        screen_data_players = {}

        for player in players:
            rectangle = self.get_rectangle_by_player(player)
            if self.use_spatial:
                screen_data_player = self.get_clip_screen(screen_data_all, rectangle=rectangle)
                screen_data_player = np.fliplr(screen_data_player)
                screen_data_player = np.rot90(screen_data_player)
                feature_layers = self.transfer_rgb_to_features(screen_data_player, player_num=len(players))
            overlap = self.get_overlap(rectangle, food_balls, thorns_balls, spore_balls, player)
            screen_data_players[player.name] = {
                'feature_layers': feature_layers,
                'rectangle': rectangle,
                'overlap': overlap,
                'team_name': player.team_name,
            }
        return screen_data_all, screen_data_players

    def get_tick_all_colorful(self, food_balls, thorns_balls, spore_balls, players, partial_size=300, player_num_per_team=3, 
                              bar_width=150, team_name_size=None):
        screen_all = pygame.Surface((self.width+bar_width, self.height))
        screen_all.fill(BACKGROUND)
        pygame.draw.line(screen_all, BLACK, (self.width+1, 0), (self.width+1, self.height), width=3)

        # render all balls
        for ball in food_balls:
            pygame.draw.circle(screen_all, FOOD_COLOR, ball.position, ball.radius)
        for ball in thorns_balls:
            pygame.draw.polygon(screen_all, THORNS_COLOR, to_aliased_circle(ball.position, ball.radius))
        for ball in spore_balls:
            pygame.draw.circle(screen_all, SPORE_COLOR, ball.position, ball.radius)
        
        player_name_size = {}
        for index, player in enumerate(players):
            for ball in player.get_balls():
                pygame.draw.circle(screen_all, PLAYER_COLORS[int(ball.team_name)][0], ball.position, ball.radius)
                font_size = int(ball.radius/1.6)
                font = pygame.font.SysFont('arial', max(font_size, 4), True)
                txt = font.render('{}'.format(chr(int(ball.owner)%player_num_per_team+65)), True, WHITE)
                txt_rect = txt.get_rect(center=(ball.position.x, ball.position.y))
                screen_all.blit(txt, txt_rect)
            player_name_size[player.name] = player.get_total_size()

        # add leaderboard
        team_name_size = sorted(team_name_size.items(), key=lambda d: d[1], reverse=True)
        start = 10
        for index, (team_name, size) in enumerate(team_name_size):
            start += 20
            font = pygame.font.SysFont('arial', 16, True)
            fps_txt = font.render('{} : {:.3f}'.format(team_name, size), True, PLAYER_COLORS[int(team_name)][0])
            screen_all.blit(fps_txt, (self.width+20, start))
            start += 20
            font = pygame.font.SysFont('arial', 14, True)
            for j in range(player_num_per_team):
                player_name = str(int(team_name)*player_num_per_team+j)
                player_size = player_name_size[player_name]
                fps_txt = font.render('  {} : {:.3f}'.format(chr(int(player_name)%player_num_per_team+65), player_size), True, PLAYER_COLORS[int(team_name)][0])
                screen_all.blit(fps_txt, (self.width+20, start))
                start += 20

        screen_data_all = pygame.surfarray.array3d(screen_all)
        screen_data_players = {}
        for player in players:
            rectangle = self.get_rectangle_by_player(player)
            screen_data_player = self.get_clip_screen(screen_data_all, rectangle=rectangle)
            screen_data_player = cv2.resize(np.rot90(np.fliplr(cv2.cvtColor(screen_data_player, cv2.COLOR_RGB2BGR))), (partial_size, partial_size))
            screen_data_players[player.name] = screen_data_player
        screen_data_all = np.rot90(np.fliplr(cv2.cvtColor(screen_data_all, cv2.COLOR_RGB2BGR)))
        return screen_data_all, screen_data_players

    def transfer_rgb_to_features(self, rgb, player_num=12):
        '''
        Overview:
            12 player + food + spore + thorns
        '''
        features = []
        assert len(rgb.shape) == 2
        h, w = rgb.shape
        for i in range(player_num):
            # import pdb; pdb.set_trace()
            features.append((rgb==PLAYER_COLORS_GRAYSCALE[i]).astype(int))
        features.append((rgb==FOOD_COLOR_GRAYSCALE).astype(int))
        features.append((rgb==SPORE_COLOR_GRAYSCALE).astype(int))
        features.append((rgb==THORNS_COLOR_GRAYSCALE).astype(int))
        return features

    def show(self):
        raise NotImplementedError

    def close(self):
        pygame.quit()
