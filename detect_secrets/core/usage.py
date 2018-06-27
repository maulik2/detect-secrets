from __future__ import absolute_import

import argparse
from collections import namedtuple


class ParserBuilder(object):

    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.plugins_parser = PluginOptions(self.parser)

        self.add_default_arguments()

    def add_default_arguments(self):
        self.plugins_parser.add_arguments()
        self._add_verbosity_argument()\
            ._add_version_argument()

    def add_pre_commit_arguments(self):
        return self._add_filenames_argument()\
            ._add_set_baseline_argument()

    def add_console_use_arguments(self):
        return self._add_initialize_baseline_argument()\
            ._add_audit_baseline_argument()

    def parse_args(self, argv):
        output = self.parser.parse_args(argv)
        self.plugins_parser.consolidate_args(output)

        return output

    def _add_version_argument(self):
        self.parser.add_argument(
            '--version',
            action='store_true',
            help='Display version information.',
        )
        return self

    def _add_verbosity_argument(self):
        self.parser.add_argument(
            '-v',
            '--verbose',
            action='count',
            help='Verbose mode.',
        )
        return self

    def _add_filenames_argument(self):
        self.parser.add_argument('filenames', nargs='*', help='Filenames to check')
        return self

    def _add_set_baseline_argument(self):
        self.parser.add_argument(
            '--baseline',
            nargs=1,
            default=[''],
            help='Sets a baseline for explicitly ignored secrets, generated by `--scan`.',
        )
        return self

    def _add_initialize_baseline_argument(self):
        self.parser.add_argument(
            '--scan',
            nargs='?',
            const='.',
            help=(
                'Scans the entire codebase and outputs a snapshot of '
                'currently identified secrets.'
            ),
            metavar='DIR_TO_SCAN',
        )

        # Pairing `--exclude` with `--scan` because it's only used for the initialization.
        # The pre-commit hook framework already has an `exclude` option that can be used instead.
        self.parser.add_argument(
            '--exclude',
            nargs=1,
            help='Pass in regex to specify ignored paths during initialization scan.',
        )

        # Pairing `--import` with `--scan` because it's only used for initialization.
        self.parser.add_argument(
            '--import',
            nargs=1,
            metavar='OLD_BASELINE_FILE',
            help='Import settings from previous existing baseline.',
        )

        return self

    def _add_audit_baseline_argument(self):
        self.parser.add_argument(
            '--audit',
            nargs=1,
            metavar='BASELINE_FILE_TO_AUDIT',
            help=(
                'Audit a given baseline file to distinguish the difference '
                'between false and true positives.'
            ),
        )

        return self


class PluginDescriptor(namedtuple(
    'PluginDescriptor',
    [
        # Classname of plugin; used for initialization
        'classname',

        # Flag to disable plugin. Eg. `--no-hex-string-scan`
        'disable_flag_text',

        # Description for disable flag.
        'disable_help_text',

        # type: list
        # Allows the bundling of all related command line provided
        # arguments together, under one plugin name.
        # Assumes there is no shared related arg.
        #
        # Furthermore, each related arg can have its own default
        # value (paired together, with a tuple). This allows us to
        # distinguish the difference between a default value, and
        # whether a user has entered the same value as a default value.
        # Therefore, only populate the default value upon consolidation
        # (rather than relying on argparse default).
        'related_args',
    ],
)):
    def __new__(cls, related_args=None, **kwargs):
        if not related_args:
            related_args = []

        return super(PluginDescriptor, cls).__new__(
            cls,
            related_args=related_args,
            **kwargs
        )


class PluginOptions(object):

    all_plugins = [
        PluginDescriptor(
            classname='HexHighEntropyString',
            disable_flag_text='--no-hex-string-scan',
            disable_help_text='Disables scanning for hex high entropy strings',
            related_args=[
                ('--hex-limit', 3,),
            ],
        ),
        PluginDescriptor(
            classname='Base64HighEntropyString',
            disable_flag_text='--no-base64-string-scan',
            disable_help_text='Disables scanning for base64 high entropy strings',
            related_args=[
                ('--base64-limit', 4.5,),
            ],
        ),
        PluginDescriptor(
            classname='PrivateKeyDetector',
            disable_flag_text='--no-private-key-scan',
            disable_help_text='Disables scanning for private keys.',
        ),
    ]

    def __init__(self, parser):
        self.parser = parser.add_argument_group(
            title='plugins',
            description=(
                'Configure settings for each secret scanning '
                'ruleset. By default, all plugins are enabled '
                'unless explicitly disabled.'
            ),
        )

    def add_arguments(self):
        self._add_custom_limits()
        self._add_opt_out_options()

    @staticmethod
    def consolidate_args(args):
        """There are many argument fields related to configuring plugins.
        This function consolidates all of them, and saves the consolidated
        information in args.plugins.

        Note that we're deferring initialization of those plugins, because
        plugins may have various initialization values, referenced in
        different places.

        :param args: output of `argparse.ArgumentParser.parse_args`
        """
        active_plugins = {}

        for plugin in PluginOptions.all_plugins:
            arg_name = PluginOptions._convert_flag_text_to_argument_name(
                plugin.disable_flag_text,
            )

            # Remove disabled plugins
            is_disabled = getattr(args, arg_name)
            delattr(args, arg_name)
            if is_disabled:
                continue

            # Consolidate related args
            related_args = {}
            for related_arg_tuple in plugin.related_args:
                try:
                    flag_name, default_value = related_arg_tuple
                except ValueError:
                    flag_name = related_arg_tuple
                    default_value = None

                arg_name = PluginOptions._convert_flag_text_to_argument_name(
                    flag_name,
                )

                related_args[arg_name] = getattr(args, arg_name)
                delattr(args, arg_name)

                if default_value and related_args[arg_name] is None:
                    related_args[arg_name] = default_value

            active_plugins.update({
                plugin.classname: related_args,
            })

        args.plugins = active_plugins

    def _add_custom_limits(self):
        high_entropy_help_text = (
            'Sets the entropy limit for high entropy strings. '
            'Value must be between 0.0 and 8.0.'
        )

        self.parser.add_argument(
            '--base64-limit',
            type=self._argparse_minmax_type,
            nargs='?',
            help=high_entropy_help_text,
        )
        self.parser.add_argument(
            '--hex-limit',
            type=self._argparse_minmax_type,
            nargs='?',
            help=high_entropy_help_text,
        )
        return self

    def _add_opt_out_options(self):
        for plugin in self.all_plugins:
            self.parser.add_argument(
                plugin.disable_flag_text,
                action='store_true',
                help=plugin.disable_help_text,
            )

        return self

    def _argparse_minmax_type(self, string):
        """Custom type for argparse to enforce value limits"""
        value = float(string)
        if value < 0 or value > 8:
            raise argparse.ArgumentTypeError(
                '%s must be between 0.0 and 8.0' % string,
            )

        return value

    @staticmethod
    def _convert_flag_text_to_argument_name(flag_text):
        """This just emulates argparse's underlying logic.

        :type flag_text: str
        :param flag_text: eg. `--no-hex-string-scan`
        :return: `no_hex_string_scan`
        """
        return flag_text[2:].replace('-', '_')
