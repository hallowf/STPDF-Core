# <STPDF convert scans to pdf>
# Copyright (C) <2019>  <Alexandre Cortegaça>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# import the necessary packages
import os
import time
import sys
import shutil
import pickle
import logging
import locale
import psutil
import math
from PIL import Image
from pytesseract import image_to_osd, Output
from multiprocessing.connection import Listener, Client
import gettext

from pytesseract.pytesseract import TesseractNotFoundError

###########################################################
#                                                         #
#  STPDFCore(str source, str dest, **kwargs)              #
#    Gathers all image paths and passes them onto         #
#     STPDFConverter(list image_path, **kwargs)           #
#                                                         #
###########################################################


class STPDFCore:
    """docstring for STPDFCore."""

    def __init__(self, source, dest, **kwargs):
        self.kwargs = kwargs
        self.source = source
        self.dest = dest
        self.deskew = kwargs.get("deskew", False)
        self.resolution = kwargs.get("resolution", 90.0)
        self.installed_lang = kwargs.get("lang", "en")
        self.m_pdf = kwargs.get("make_pdf", True)
        self.save_files = kwargs.get("save_files", False)
        self.log_level = kwargs.get("log_level", "info")
        # TODO: switch to True
        batch_process, batch_split = kwargs.get("batch_split", (False, 50))
        self.batch_process = batch_process
        self.batch_split = batch_split
        split, at = kwargs.get("split", (False, 0))
        self.split = split
        self.split_at = at
        # Resize is working but is not being passed neither by the cli or the gui
        self.resize = kwargs.get("resize", False)
        self.image_paths = []
        self.processed_images = []
        self.max_mem_usage = self.define_max_memory_usage_until_exception()
        self.file_number = 0
        self.file_counter = 0
        # Check how many files to copy
        for __, __, files in os.walk(self.source):
            self.file_number += len(files)
        self.one_percent_files = self.file_number / 100
        # Install language
        if self.installed_lang == "en":
            gettext.install("stpdf-core")
        else:
            modl = "%s_converter" % self.installed_lang
            current_locale, encoding = locale.getdefaultlocale()
            cl = current_locale.split("_")
            if self.installed_lang != cl[0]:
                current_locale = "%s_%s" % (self.installed_lang,
                                            self.installed_lang.upper())
            lang = gettext.translation(modl,
                                       "locale",
                                       [current_locale])
            lang.install()
        self.set_up_logger()

    # This should be removed in the future as for now
    # it is a failsafe mechanism for the users who try to
    # forcibly process more files at the same time
    # regardlessly of the system's specs
    # see BUG in get_handles function
    def define_max_memory_usage_until_exception(self):
        mem_values = dict(psutil.virtual_memory()._asdict())
        # i'm using available memory
        # because some of it is cache and can be overwritten
        # however to avoid system hangs i subtract shared memory
        # if it has less digits than available else fallback
        # to free memory that should be lower but still work
        avail_digits = int(math.log10(mem_values["available"]))
        shared_digits = int(math.log10(mem_values["shared"]))
        if shared_digits < avail_digits:
            return int(mem_values["available"] - mem_values["shared"])
        else:
            return int(mem_values["free"])

    # sets up console logger, independent of the GUI/CLI
    def set_up_logger(self):
        # switch PIL logger to errors only
        logging.getLogger("PIL").setLevel(logging.ERROR)
        # set up core logger
        l_level = self.log_level
        n_level = getattr(logging, l_level.upper(), 20)
        if n_level == 20 and l_level.upper() != "INFO":
            sys.stdout.write("%s: %s\n" % (_("Invalid log level"), l_level))
        # Console logger
        formatter = logging.Formatter("%(name)s - %(levelname)s: %(message)s")
        self.logger = logging.getLogger("STPDF.Core")
        self.logger.setLevel(n_level)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        ch.setLevel(n_level)
        self.logger.addHandler(ch)
        msg = "%s: %s" % (_("Console logger is set with log level"), l_level)
        self.logger.info(msg)

    def run_converter(self):
        if not self.save_files and not self.m_pdf:
            yield _("Nothing to do, neither save files or make pdf is selected") + "\n"
        else:
            if self.file_number >= 100 and self.deskew:
                yield "%s %i %s\n" % (_("Found"),
                                      self.file_number,
                                      _("files to copy and deskew this might take a bit"))
            if self.file_number >= 250 and self.save_files is False:
                msg = _("Found too many files to handle, this is not implemented yet")
                raise NotImplementedError(msg)
            else:
                for line in self.gather_images():
                    yield line
                if self.batch_process is False:
                    self.converter = STPDFConverter(self.image_paths, **self.kwargs)
                    yield "0"
                else:
                    sa = self.batch_split
                    sets_list = [self.image_paths[i * sa:(i + 1) * sa] for i in range((len(self.image_paths) + sa - 1) // sa)]
                    print(sets_list)
                    yield "0"
                yield _("Finished")

    # Gathers all the paths of images with known extensions
    def gather_images(self):
        known_extensions = ["JPG", "PNG"]
        yield _("Starting image gathering") + "\n"
        yield "%s: %i\n" % (_("Files Found"), self.file_number)
        for root, __, files in os.walk(self.source, topdown=False):
            for file in files:
                self.file_counter += 1
                if(round(self.file_counter % self.one_percent_files, 1) == 0.0):
                    msg = "%i / %i %s.\n" % (self.file_counter,
                                             self.file_number,
                                             _("gathered"))
                    self.logger.debug(msg)
                    yield msg
                extension = os.path.splitext(file)[1][1:].upper()
                source_path = os.path.join(root, file)
                if extension in known_extensions:
                        self.image_paths.append(source_path)
        self.file_number = self.file_counter
        self.one_percent_files = self.file_number / 100
        self.file_counter = 0
        yield _("Gathering done") + "\n"

###########################################################
#                                                         #
#  STPDFConverter(list image_paths, **kwargs)             #
#    Processes the images provided in the list, inherits  #
#     kwargs from STPDFCore                               #
#                                                         #
###########################################################


class STPDFConverter:

    def __init__(self, image_paths, **kwargs):
        self.image_paths = image_paths
        self.deskew = kwargs.get("deskew", False)
        self.resolution = kwargs.get("resolution", 90.0)
        self.installed_lang = kwargs.get("lang", "en")
        self.m_pdf = kwargs.get("make_pdf", True)
        self.save_files = kwargs.get("save_files", False)
        self.log_level = kwargs.get("log_level", "info")
        self.file_number = len(image_paths)
        self.one_percent_files = self.file_number / 100
        self.file_counter = 0
        self.set_up_logger()

    # set up converter logger, only logs debug messages
    # all other messages should be yielded to the caller
    # independent of STPDFCore and GUI/CLI
    def set_up_logger(self):
        l_level = self.log_level
        n_level = getattr(logging, l_level.upper(), 20)
        if n_level == 20 and l_level.upper() != "INFO":
            sys.stdout.write("%s: %s\n" % (_("Invalid log level"), l_level))
        # Console logger
        formatter = logging.Formatter("%(name)s - %(levelname)s: %(message)s")
        self.logger = logging.getLogger("STPDF.Core.Converter")
        self.logger.setLevel(n_level)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        ch.setLevel(n_level)
        self.logger.addHandler(ch)
        msg = "%s: %s" % (_("Console logger is set with log level"), l_level)
        self.logger.debug(msg)

    # returns progress string
    def print_progress_percent(self, action):
        if(round(self.file_counter % self.one_percent_files, 1) == 0.0):
            msg = "%i / %i %s.\n" % (self.file_counter,
                                     self.file_number,
                                     action)
            return msg
        else:
            return False

    def log_action_msg(self, action, ref_object=None):
        msg = ""
        if ref_object is None:
            msg = "%s" % (action)
        else:
            msg = "%s: %s" % (action, ref_object)
        self.logger.debug(msg)

    def process_images(self):
        yield _("Starting image processing") + "\n"
        for img_p in self.image_paths:
            self.file_counter += 1
            print_progress = self.print_progress_percent(_("processed"))
            if print_progress is not False:
                yield print_progress
            dest_p = os.path.join(self.dest, os.path.basename(img_p))
        yield _("Processing done") + "\n"

    def process_image(self, img):
        dest_p = os.path.join(self.dest, os.path.basename(img))
        if self.deskew:
            try:
                img = self.deskew_image(img)
            except expression as identifier:
                pass
        if self.resize:
            img = self.resize_image(img)
        if self.save_files:
            img.save(dest_p)

    def processed_images_generator(self):
        for img_p in self.image_paths:
            try:
                self.verify_image(img_p)
            except Exception as e:
                self.logger.error(e)
                self.log_action_msg(_("Failed to verify image"), img_p)
                self.log_action_msg(_("Skipping image"))
                continue
            self.file_counter += 1
            print_progress = self.print_progress_percent(_("processed"))
            if print_progress is not False:
                yield print_progress
            img = self.process_image(img_p)

    def verify_image(self, img_p):
        with open(img_p, "rb") as fp:
            self.log_action_msg(_("Verifying image"), img_p)
            # read the file into Pil's Image.open method
            with Image.open(fp) as img:
                # Try to verify the file or skip it
                try:
                    img.verify()
                except Exception as e:
                    raise e

    # resizes the image based on a percentage
    def resize_image(self, img):
        self.log_action_msg(_("Resizing image"), img)
        size = (img.size[0] / self.resize, img.size[1] / self.resize)
        img.thumbnail(size, Image.ANTIALIAS)
        return img

    # BUG: Some images get flipped sideways
    def deskew_image(self, img):
        self.log_action_msg(_("Deskewing image"), img)
        try:
            rotate = image_to_osd(img, output_type=Output.DICT)["rotate"]
            # This tells it to use the
            # highest quality interpolation algorithm that it has available,
            # and to expand the image to encompass the full rotated size
            # instead of cropping.
            # The documentation does not say what color
            # the background will be filled with.
            # https://stackoverflow.com/a/17822099
            img = img.rotate(-rotate, resample=Image.BICUBIC, expand=True)
        # sometimes an error can occur with tesseract reading the image
        # maybe there is not enough text or dpi is not set
        # this need to be handled
        except Exception as e:
            self.logger.error(e)
            raise e
        return img

    # Function to generate pdf's
    def make_pdf(self):
        if self.split:
            sa = self.split_at
            yield "%s: %i\n" % (_("Creating multiple PDFs splitting by"), sa)
            if len(image_handles) > sa:
                # Mom's spaghetti ahead
                sets_list = [image_handles[i * sa:(i + 1) * sa] for i in range((len(image_handles) + sa - 1) // sa)]
                image_handles = None
                self.file_number = len(sets_list)
                self.one_percent_files = self.file_number / 100
                for handle_list in sets_list:
                    yield _("Generating a pdf")
                    first = handle_list.pop(0)
                    self.file_counter += 1
                    name = os.path.join(self.dest, "%i.pdf" % self.file_counter)
                    while os.path.isfile(name):
                        self.file_counter += 1
                        name = os.path.join(self.dest,
                                            "%i.pdf" % self.file_counter)
                    try:
                        first.save(name, "PDF", resolution=90.0, save_all=True,
                                   append_images=handle_list)
                        msg = "%s: %s" % (_("PDF created"), name)
                        yield msg
                    except Exception as e:
                        self.logger.critical(e)
                        msg = "%s: %s\n%s" % (_("Failed to create pdf:"),
                                              e, _("skipping to the next one"))
                        yield msg
                    sets_list.pop(self.file_counter)
        else:
            yield _("Creating a single pdf") + "\n"
            # Remove the first image and store it in a variable
            first = image_handles.pop(0)
            # Save the first image as pdf and append the others
            name = os.path.join(self.dest, "%i.pdf" % self.file_counter)
            while os.path.isfile(name):
                self.file_counter += 1
                name = os.path.join(self.dest, "%i.pdf" % self.file_counter)
            try:
                first.save(name, "PDF", resolution=90.0, save_all=True,
                           append_images=image_handles)
            except Exception as e:
                msg = "%s: %s" % (_("Failed to create pdf:"), e)
                self.logger.critical(e)
