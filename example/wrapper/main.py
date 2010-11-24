#!/usr/bin/python
# -*- coding: utf-8 -*-

from minecraft.wrapper import MinecraftWrapper

def main():
    w = MinecraftWrapper()
    w.load_command_module('example.wrapper.commands')
    w.load_handler_module('example.wrapper.handlers')
    w.start()

if __name__ == '__main__':
    main()