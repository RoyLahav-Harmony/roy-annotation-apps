import curses
import random

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)

    sh, sw = stdscr.getmaxyx()
    height, width = sh - 2, sw - 2

    snake = [(height // 2, width // 4 + 2 - i) for i in range(3)]
    direction = curses.KEY_RIGHT
    food = place_food(snake, height, width)
    score = 0

    while True:
        stdscr.clear()

        draw_border(stdscr)
        draw_score(stdscr, score, sw)

        for y, x in snake:
            stdscr.addch(y + 1, x + 1, '#')

        stdscr.addch(food[0] + 1, food[1] + 1, '*')

        key = stdscr.getch()
        if key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT):
            if not is_opposite(key, direction):
                direction = key

        head_y, head_x = snake[0]
        if direction == curses.KEY_UP:
            head_y -= 1
        elif direction == curses.KEY_DOWN:
            head_y += 1
        elif direction == curses.KEY_LEFT:
            head_x -= 1
        elif direction == curses.KEY_RIGHT:
            head_x += 1

        if head_y < 0 or head_y >= height or head_x < 0 or head_x >= width:
            game_over(stdscr, score)
            return

        if (head_y, head_x) in snake:
            game_over(stdscr, score)
            return

        snake.insert(0, (head_y, head_x))

        if (head_y, head_x) == food:
            score += 10
            food = place_food(snake, height, width)
        else:
            snake.pop()

        stdscr.refresh()


def is_opposite(new_dir, cur_dir):
    opposites = {
        curses.KEY_UP: curses.KEY_DOWN,
        curses.KEY_DOWN: curses.KEY_UP,
        curses.KEY_LEFT: curses.KEY_RIGHT,
        curses.KEY_RIGHT: curses.KEY_LEFT,
    }
    return opposites.get(new_dir) == cur_dir


def place_food(snake, height, width):
    while True:
        pos = (random.randint(0, height - 1), random.randint(0, width - 1))
        if pos not in snake:
            return pos


def draw_border(stdscr):
    stdscr.border()


def draw_score(stdscr, score, sw):
    label = f" Score: {score} "
    stdscr.addstr(0, (sw - len(label)) // 2, label)


def game_over(stdscr, score):
    sh, sw = stdscr.getmaxyx()
    msg = f"GAME OVER  |  Score: {score}  |  Press any key to quit"
    stdscr.addstr(sh // 2, max(0, (sw - len(msg)) // 2), msg)
    stdscr.nodelay(False)
    stdscr.getch()


if __name__ == "__main__":
    curses.wrapper(main)
