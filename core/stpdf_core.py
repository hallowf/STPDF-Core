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


class STPDFCore:
    """docstring for STPDFCore."""

    def __init__(self, source, dest, split=(True, 1), *args, **kwargs):
        super(STPDFCore, self).__init__()
        self.source = source
        self.dest = dest
        self.deskew = kwargs.get("deskew", False)
        self.resolution = kwargs.get("resolution", 90.0)
        self.installed_lang = kwargs.get("lang", "en")
        self.m_pdf = kwargs.get("make_pdf", True)
        self.save_files = kwargs.get("save_files", False)
        # Resize is working but is not being passed neither by the cli or the gui
        self.resize = kwargs.get("resize", False)
        self.log_level = kwargs.get("log_level", "info")
        self.log_levels = ["debug", "info", "warning", "error", "critical"]
        self.image_paths = []
        self.processed_images = []
        self.max_mem_usage = self.define_max_memory_usage_until_exception()
        split, at = split
        self.split = split
        self.split_at = at
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
        avail_digits = int(math.log10(mem_values["available"]))
        shared_digits = int(math.log10(mem_values["shared"]))
        if shared_digits < avail_digits:
            return int(mem_values["available"] - mem_values["shared"])
        else:
            return int(mem_values["free"])

    def set_up_logger(self):
        # disable PIL logger
        # logging.getLogger("PIL").setLevel(logging.ERROR)
        # set up core logger
        l_levels = self.log_levels
        l_level = self.log_level
        n_level = None
        if l_level not in l_levels:
            sys.stdout.write("%s: %s\n" % (_("Invalid log level"), l_level))
            l_level = "info"
            n_level = getattr(logging, l_level.upper(), 10)
        else:
            n_level = getattr(logging, l_level.upper(), 10)
        # Console logger
        log_format = "%(name)s - %(levelname)s: %(message)s"
        logging.basicConfig(format=log_format, level=n_level)
        self.logger = logging.getLogger("STPDF-Core")
        msg = "%s: %s" % (_("Console logger is set with log level"), l_level)
        self.logger.info(msg)

    # returns progress string
    def print_progress_percent(self, action):
        """prints progress for the current action

        str action: must be a translatable string, EX: _("gathered")
        """
        if(round(self.file_counter % self.one_percent_files, 1) == 0.0):
            msg = "%i / %i %s.\n" % (self.file_counter,
                                     self.file_number,
                                     action)
            self.logger.info(msg)
            return msg
        else:
            return False

    # Update file number and reset counter
    def update_fileNumber_and_reset_counter(self):
        self.file_number = self.file_counter
        self.one_percent_files = self.file_number / 100
        self.file_counter = 0

    # calls all the required functions
    # for gathering and processing the images
    # Steps should be:
    # 1 - Image gathering
    # 2 - Image processing
    # 3 - PDF generation
    def process_all(self):
        if not self.save_files and not self.m_pdf:
            yield _("Nothing to do, neither save files or make pdf is selected") + "\n"
        else:
            if self.file_number >= 200 and self.deskew:
                yield "%s %i %s\n" % (_("Found"),
                                      self.file_number,
                                      _("files to copy and deskew this might take a bit"))
            if (self.file_number >= 300 and self.save_files) or (self.file_number >= 500 and self.make_pdf and not self.save_files):
                msg = _("Found too many files to handle, this is not implemented yet")
                raise NotImplementedError(msg)
            else:
                for line in self.gather_images():
                    yield line
                for line in self.process_images():
                    yield line
                if self.m_pdf:
                    for line in self.make_pdf():
                        yield line
                yield _("Converter finished")

    # Gathers all the paths of images with known extensions
    def gather_images(self):
        known_extensions = ["JPG", "PNG"]
        yield _("Starting image gathering") + "\n"
        yield "%s: %i\n" % (_("Files Found"), self.file_number)
        for root, __, files in os.walk(self.source, topdown=False):
            for file in files:
                self.file_counter += 1
                print_progress = self.print_progress_percent(_("gathered"))
                if print_progress is not False:
                    yield print_progress
                extension = os.path.splitext(file)[1][1:].upper()
                source_path = os.path.join(root, file)
                if extension in known_extensions:
                        self.image_paths.append(source_path)
        self.update_fileNumber_and_reset_counter()
        yield _("Gathering done") + "\n"

    def verify_image(self, img_p):
        with open(img_p, "rb") as fp:
            # read the file into Pil's Image.open method
            print("veryfing image")
            with Image.open(fp) as img:
                # Try to verify the file or skip it
                try:
                    img.verify()
                    print("verified")
                except Exception as e:
                    print("failed to verify", e)
                    # remove from counter and paths since it can't be processed
                    self.logger.error(e)
                    self.file_counter -= 1
                    self.image_paths.pop(self.file_counter)
                    msg = "%s: %s\n%s" % (_("Failed to process image"),
                                          _("Skipping"), img_p)
                    return msg
        return True

    def process_images(self):
        yield _("Starting image processing") + "\n"
        for img_p in self.image_paths:
            self.file_counter += 1
            print_progress = self.print_progress_percent(_("processed"))
            if print_progress is not False:
                yield print_progress
            dest_p = os.path.join(self.dest, os.path.basename(img_p))
            # Open the file in binary mode
            print("opening image: %s" % img_p)
            try:
                if self.verify_image(img_p):
                    with open(img_p, "rb") as fp:
                        # Since img.verify() closes the image before loading the data
                        # img needs to be open and loaded again
                        print("reading image again")
                        with Image.open(fp) as f_img:
                            try:
                                print("loading image")
                                f_img.load()
                            except Exception as e:
                                print("Failed to load", e)
                            img = f_img
                            if self.resize:
                                print("resizing image")
                                img = self.resize_image(img)
                            if self.deskew:
                                print("deskewing image")
                                try:
                                    img = self.deskew_image(img)
                                except Exception as e:
                                    print("failed to deskew", e)
                                    self.logger.error(e)
                                    msg = "\n%s: %s\n" % (_("An exception occured while deskewing image"), e)
                                    yield msg
                                    msg = "\n%s: %s\n" % (_("This image wont be processed"), dest_path)
                                    yield msg
                            if self.save_files:
                                print("saving image")
                                # save the image
                                # and replace the current path with the saved image path
                                img.save(dest_p)
                                self.image_paths[self.file_counter - 1] = dest_p
                            else:
                                print("appending image")
                                self.processed_images.append(img)
            except Exception as e:
                print(e)
        self.update_fileNumber_and_reset_counter()
        yield _("Processing done")

    # resizes the image based on a percentage
    def resize_image(self, img):
        size = (img.size[0] / self.resize, img.size[1] / self.resize)
        img.thumbnail(size, Image.ANTIALIAS)
        return img

    # BUG: Some images get flipped sideways
    def deskew_image(self, img):
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

    def get_handles(self):
        image_handles = []
        if self.save_files:
            image_handles = self.processed_images
        else:
            # BUG: This won't work with too many images
            # it will easily run out of memory
            # this was observed in images generated with PIL
            image_handles = [Image.open(img).load() for img in self.image_paths]
        if len(image_handles) > 0:
            return False
        else:
            return image_handles

    # Function to generate pdf's
    def make_pdf(self):
        # Get all image handles
        image_handles = self.get_handles()
        if image_handles is not False:
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
                        print_progress = self.self.print_progress_percent(_("generated"))
                        if print_progress is not False:
                            yield print_progress
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
        else:
            yield _("Failed to obtain image handles")
