"""
A StorPool Juju charm helper module: exception definitions.
"""


class StorPoolNoConfigException(Exception):
    """
    The StorPool charm configuration is not yet complete.
    """

    def __init__(self, missing):
        """
        Create a configuration exception with the specified missing
        configuration settings.
        """
        self.missing = missing

    def __str__(self):
        """
        Show the missing configuration settings.
        """
        return (
            "The StorPool charm configuration is not yet complete; "
            + "missing items: {m}".format(m=" ".join(self.missing))
        )


class StorPoolNoCGroupsException(Exception):
    """
    The StorPool control groups configuration is not properly done.
    """

    def __init__(self, msg):
        """
        Create a configuration exception with the specified missing
        control groups.
        """
        self.msg = msg

    def __str__(self):
        """
        Show the control group configuration problem.
        """
        return "The StorPool control groups are not properly set: {m} ".format(
            m=self.msg
        )


class StorPoolPackageInstallException(Exception):
    """
    The installation of some StorPool packages failed.
    """

    def __init__(self, names, cause):
        """
        Create a package install exception object with the specified
        list of packages and error cause.
        """
        self.names = names
        self.cause = cause

    def __str__(self):
        """
        Show the packages and the error cause.
        """
        return "Could not install the {names} StorPool packages: {e}".format(
            names=" ".join(self.names), e=self.cause
        )


class StorPoolMissingComponentsException(Exception):
    """
    Some of the prerequisites (usually a StorPool package) is
    not installed.
    """

    def __init__(self, names):
        """
        Create a missing component exception with the specified list of
        components.
        """
        self.names = names

    def __str__(self):
        """
        Show the names of the missing components.
        """
        return "Missing StorPool components: {names}".format(
            names=" ".join(self.names)
        )


class StorPoolException(Exception):
    """
    A generic exception raised by the StorPool charm routines.
    """

    pass
