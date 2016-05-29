import term

# warning: hack filled nonsense follows, since I'm
# converting a system that expects full control over
# the screen to something that prints linearly in
# the terminal

def write_char(c, fg_col, bg_col, style):
    # '\n' check b/c reverse video col isn't suppose to stretch across window
    # guessing that based on S 8.7.3.1
    if style == 'reverse_video' and c != '\n':
        fg_col, bg_col = bg_col, fg_col
    # no other styling for now
    term.write_char_with_color(c, fg_col, bg_col)

class ScreenChar(object):
    def __init__(self, char, fg_color, bg_color, text_style):
        self.char = char
        self.fg_color = fg_color
        self.bg_color = bg_color
        self.text_style = text_style
    def __str__(self):
        return self.char

class Screen(object):
    def __init__(self, env):
        self.env = env
        self.init_bufs()
        self.wrapBuf = []

    def init_bufs(self):
        self.textBuf = self.make_screen_buf()

    def make_screen_buf(self):
        return [self.make_screen_line() for i in xrange(self.env.hdr.screen_height_units)]

    def make_screen_line(self):
        c, fg, bg, style = ' ', self.env.fg_color, self.env.bg_color, 'normal'
        return [ScreenChar(c, fg, bg, style) for i in xrange(self.env.hdr.screen_width_units)]

    def blank_top_win(self):
        env = self.env
        term.home_cursor()
        for i in xrange(env.top_window_height):
            write_char('\n', env.fg_color, env.bg_color, env.text_style)
            self.textBuf[i] = self.make_screen_line()

    def blank_bottom_win(self):
        if buf_empty(self.textBuf):
            return
        for i in xrange(self.env.top_window_height, self.env.hdr.screen_height_units):
            self.scroll()

    def write(self, text):
        env = self.env

        # the spec suggests pushing the bottom window cursor down.
        # to allow for more trinity box tricks (admittedly only seen so
        # far in baby_tree.zblorb), we'll do that only when it's
        # being written to.
        if env.current_window == 0 and env.cursor[0][0] < env.top_window_height:
            env.cursor[0] = env.top_window_height, env.cursor[0][1]

        as_screenchars = map(lambda c: ScreenChar(c, env.fg_color, env.bg_color, env.text_style), text)
        if env.current_window == 0 and env.use_buffered_output:
            self.write_wrapped(as_screenchars)
        else:
            self.write_unwrapped(as_screenchars)

    # for when it's useful to make a hole in the scroll text
    # e.g. moving already written text around to make room for
    # what's about to become a new split window
    def scroll_top_line_only(self):
        env = self.env
        top_win = self.textBuf[:env.top_window_height]
        term.home_cursor()
        self.overwrite_line(self.textBuf[env.top_window_height])
        term.scroll_down()
        self.textBuf = top_win + [self.make_screen_line()] + self.textBuf[env.top_window_height+1:]
        # self.flush() # TODO: fun but slow, make a config option

    def scroll(self, lines=1):
        env = self.env
        for i in range(lines):
            top_win = self.textBuf[:env.top_window_height]
            term.home_cursor()
            self.overwrite_line(self.textBuf[env.top_window_height])
            term.scroll_down()
            self.textBuf = top_win + self.textBuf[env.top_window_height+1:] + [self.make_screen_line()]
            # self.flush() # TODO: fun but slow, make a config option

    def overwrite_line(self, new_line):
        term.clear_line()
        for c in new_line:
            write_char(c.char, c.fg_color, c.bg_color, c.text_style)
        term.fill_to_eol_with_bg_color()

    def new_line(self):
        env, win = self.env, self.env.current_window
        row, col = env.cursor[win]
        if win == 0:
            if row+1 == env.hdr.screen_height_units:
                self.scroll()
                env.cursor[win] = row, 0
            else:
                env.cursor[win] = row+1, 0
        else:
            if row+1 < env.top_window_height:
                env.cursor[win] = row+1, 0
            else:
                env.cursor[win] = row, 0

    def write_wrapped(self, text_as_screenchars):
        self.wrapBuf += text_as_screenchars

    # for bg_color propagation (only happens when a newline comes in via wrapping, it seems)
    def new_line_via_spaces(self, fg_color, bg_color, text_style):
        env, win = self.env, self.env.current_window
        row, col = env.cursor[win]
        self.write_unwrapped([ScreenChar(' ', fg_color, bg_color, text_style)])
        while env.cursor[win][1] > col:
            self.write_unwrapped([ScreenChar(' ', fg_color, bg_color, text_style)])

    def finish_wrapping(self):
        env = self.env
        win = env.current_window
        text = self.wrapBuf
        self.wrapBuf = []
        def find_char_or_return_len(cs, c):
            for i in range(len(cs)):
                if cs[i].char == c:
                    return i
            return len(cs)
        def collapse_on_newline(cs):
            if env.cursor[win][1] == 0:
                # collapse all spaces
                while len(cs) > 0 and cs[0].char == ' ':
                    cs = cs[1:]
                # collapse the first newline (as we just generated one)
                if len(cs) > 0 and cs[0].char == '\n':
                    cs = cs[1:]
            return cs
        while text:
            if text[0].char == '\n':
                self.new_line_via_spaces(text[0].fg_color, text[0].bg_color, text[0].text_style)
                text = text[1:]
            elif text[0].char == ' ':
                self.write_unwrapped([text[0]])
                text = text[1:]
                text = collapse_on_newline(text)
            else:
                first_space = find_char_or_return_len(text, ' ')
                first_nl = find_char_or_return_len(text, '\n')
                word = text[:min(first_space, first_nl)]
                text = text[min(first_space, first_nl):]
                if len(word) > env.hdr.screen_width_units:
                    self.write_unwrapped(word)
                elif env.cursor[win][1] + len(word) > env.hdr.screen_width_units:
                    self.new_line_via_spaces(word[0].fg_color, word[0].bg_color, word[0].text_style)
                    self.write_unwrapped(word)
                else:
                    self.write_unwrapped(word)
                text = collapse_on_newline(text)

    def write_unwrapped(self, text_as_screenchars):
        env = self.env
        win = env.current_window
        w = env.hdr.screen_width_units
        for c in text_as_screenchars:
            if c.char == '\n':
                self.new_line()
            else:
                y, x = env.cursor[win]
                self.textBuf[y][x] = c
                env.cursor[win] = y, x+1
                if x+1 == w:
                    self.new_line()

    def flush(self):
        self.finish_wrapping()
        term.home_cursor()
        buf = self.textBuf
        for i in xrange(len(buf)):
            for j in xrange(len(buf[i])):
                c = buf[i][j]
                write_char(c.char, c.fg_color, c.bg_color, c.text_style)
            if i < len(buf) - 1:
                write_char('\n', c.fg_color, c.bg_color, c.text_style)
            else:
                term.fill_to_eol_with_bg_color()

    def get_line_of_input(self):
        env = self.env
        term.home_cursor()
        row, col = env.cursor[env.current_window]
        term.cursor_down(row)
        term.cursor_right(col)
        term.set_color(env.fg_color, env.bg_color)
        if line_empty(self.textBuf[row][col:]):
            term.fill_to_eol_with_bg_color()
        term.show_cursor()
        text = raw_input()[:120] # 120 char limit seen on gargoyle
        term.hide_cursor()
        for t in text:
            self.write_unwrapped([ScreenChar(t, env.fg_color, env.bg_color, env.text_style)])
        self.new_line_via_spaces(env.fg_color, env.bg_color, env.text_style)
        term.home_cursor()
        return text

    def first_draw(self):
        term.hide_cursor()
        term.clear_screen()
        term.home_cursor()
        env = self.env
        for i in xrange(env.hdr.screen_height_units-1):
            write_char('\n', env.fg_color, env.bg_color, env.text_style)
        term.fill_to_eol_with_bg_color()

    def getch(self):
        c = term.getch()
        if ord(c) == 127: #delete should be backspace
            c = '\b'
        # TODO: Arrow keys, function keys, keypad?
        # select() makes things complicated.
        # mainly because I develop on cygwin where select just
        # doesn't work with files. Doing this right for me
        # is tough: need an isCygwin() check, but more importantly,
        # no win32 api direct from python in cygwin, so I'd have
        # to get around *that*. So right now, no escape sequence keys.

        return c

def buf_empty(buf):
    for line in buf:
        if not line_empty(line):
            return False
    return True

def line_empty(line):
    for c in line:
        if c.char != ' ':
            return False
    return True

def write(env, text):

    # stream 3 overrides all other output
    if 3 in env.selected_ostreams:
        env.output_buffer[3] += text
        return

    # TODO: (if I so choose): stream 2 (transcript stream)
    # should also be able to wordwrap if buffer is on
    for stream in env.selected_ostreams:
        if stream == 1:
            env.screen.write(text)
        else:
            env.output_buffer[stream] += text

def flush(env):
    if 3 not in env.selected_ostreams:
        if 1 in env.selected_ostreams:
            env.screen.flush()
