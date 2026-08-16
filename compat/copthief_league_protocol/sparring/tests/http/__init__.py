"""The tier that genuinely needs the dependency.

Everything testable without a network stack lives one directory up and runs with nothing
installed. What is left here is what only a real server can answer: that the four tools exist
under the names the reference defines, that ``submit_audit`` really does take ``payload`` while
the others take ``message``, and that no handler blocks.
"""
