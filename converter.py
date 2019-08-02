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
import sys
import shutil
import pickle
import logging
import locale
from PIL import Image
from pytesseract import image_to_osd, Output
from multiprocessing.connection import Listener, Client
import gettext

from pytesseract.pytesseract import TesseractNotFoundError


class Converter(object):
    """docstring for Converter."""

    def __init__(self, source, dest, split=(True, 1), *args, **kwargs):
        super(Converter, self).__init__()
        self.source = source
        self.dest = dest
        self.deskew = kwargs.get("deskew", False)
        self.resolution = kwargs.get("resolution", 90.0)
        self.installed_lang = kwargs.get("lang", None)
        self.m_pdf = kwargs.get("make_pdf", True)
        self.save_files = kwargs.get("save_files", False)
        # Resize is working but is not being passed neither by the cli or the gui
        self.resize = kwargs.get("resize", None)
        self.image_paths = []
        self.images = []
        self.image_handles = None
        self.counter = 0
        self.stop_running = False
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
        if self.installed_lang == "en" or self.installed_lang is None:
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
        # Mute other loggers
        self.mute_other_loggers()

    def mute_other_loggers(self):
        logging.getLogger("PIL").setLevel(logging.ERROR)

    # checks how many files are there to copy over
    def process_all(self):
        if not self.save_files and not self.m_pdf:
            yield _("Nothing to do, neither save files or make pdf is selected")
        else:
            if self.file_number >= 100 and self.deskew:
                yield "%s %i %s" % (_("Found"),
                                    self.file_number,
                                    _("files to copy and deskew is true this might take a bit"))
            if (self.file_number >= 600 and self.save_files) or (self.file_number >= 1000 and self.make_pdf):
                yield _("Found too many files to handle, this is not implemented yet")
            else:
                for line in self.gather_images():
                    yield line
                if self.deskew:
                    for line in self.deskew_images():
                        yield line
                if self.m_pdf:
                    for line in self.make_pdf():
                        yield line
                yield _("Converter finished")

    # TODO: the images do not need to be copied neither saved if the user only wants a pdf
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
                    yield msg
                extension = os.path.splitext(file)[1][1:].upper()
                source_path = os.path.join(root, file)
                destination_dir = self.dest
                if extension in known_extensions:
                    # Rotate the images first if deskew is true
                    if self.deskew:
                        try:
                            self.images.append([source_path,
                                               "%s/%s" % (destination_dir, file)])
                        except (Exception, TesseractNotFoundError) as e:
                            msg = "%s: %s" % (_("Error occurred while opening image"), e)
                            yield msg
                            break
                    else:
                        self.image_paths.append(source_path)
        yield _("Gathering done")

    # BUG: Some images get flipped sideways
    def deskew_images(self):
        img_sets = [img_set for img_set in self.images]
        sets_len = len(img_sets)
        yield _("Deskewing images") + "\n"
        one_percent = sets_len / 100
        counter = 0
        if sets_len > 0:
            self.images = []
            # set: [source_path, dest_path]
            for img_set in img_sets:
                counter += 1
                if(round(counter % one_percent, 1) == 0.0):
                    msg = "%i / %i %s.\n" % (counter,
                                             sets_len,
                                             _("deskewed"))
                    yield msg
                dest_path = img_set[1]
                img = Image.open(img_set[0])
                try:
                    rotate = image_to_osd(img, output_type=Output.DICT)["rotate"]
                    # This tells it to use the
                    # highest quality interpolation algorithm that it has available,
                    # and to expand the image to encompass the full rotated size
                    # instead of cropping.
                    # The documentation does not say
                    # what color the background will be filled with.
                    # https://stackoverflow.com/a/17822099
                    img = img.rotate(-rotate, resample=Image.BICUBIC, expand=True)
                    if self.save_files:
                        self.image_paths.append(dest_path)
                        img.save(dest_path)
                    else:
                        self.images.append(img)
                # sometimes an error can occur with tesseract reading the image
                # maybe there is not enough text or dpi is not set
                # this need to be handled
                except Exception as e:
                    msg = "%s: %s" % (_("And exception occured while deskewing image"), e)
                    yield msg
                    msg = "%s: %s" % (_("This image wont be processed"), img_set[1])
                    self.image_paths.append(img_set[0])
                    continue
        else:
            msg = _("Failed to obtain images to deskew")
            yield msg

    # gets all image handles
    def check_handles(self):
        image_handles = [Image.open(image) for image in self.image_paths]
        PIL_handles = None
        if len(self.images) > 0:
            PIL_handles = [image for image in self.images]
        if PIL_handles is not None:
            image_handles += PIL_handles
        if len(image_handles) == 0:
            return False
        else:
            return image_handles

    # resizes the images based on a percentage
    def resize_images(self, image_handles):
        yield _("Resizing images") + "\n"
        index = 0
        fl = len(image_handles)
        l_l = fl / 100
        for img in image_handles:
            if round(index % l_l, 1) == 0.0:
                msg = "%i / %i %s\n" % (index,
                                        fl,
                                        _("resized"))
                yield msg
            size = (img.size[0] / self.resize, img.size[1] / self.resize)
            img.thumbnail(size, Image.ANTIALIAS)
            image_handles[index] = img
            index += 1

    # Function to generate pdf's
    def make_pdf(self):
        # Get all image handles
        image_handles = self.check_handles()
        if self.resize is not None:
            for line in self.resize_images(image_handles):
                yield line
        if image_handles is not False:
            # now that we have the handles let's
            # clean the class's stored handles to spare some memory
            self.image_paths = []
            self.images = []
            if self.split:
                sa = self.split_at
                yield "%s: %i" % (_("Creating multiple PDFs splitting by"), sa)
                if len(image_handles) > sa:
                    # Mom's spaghetti ahead
                    image_handles = [image_handles[i * sa:(i + 1) * sa] for i in range((len(image_handles) + sa - 1) // sa)]
                    for handle_list in image_handles:
                        first = handle_list[0]
                        handle_list.pop(0)
                        self.counter += 1
                        name = os.path.join(self.dest, "%i.pdf" % self.counter)
                        while os.path.isfile(name):
                            self.counter += 1
                            name = os.path.join(self.dest,
                                                "%i.pdf" % self.counter)
                        first.save(name, "PDF", resolution=90.0, save_all=True,
                                   append_images=handle_list)
                        msg = "%s: %s" % (_("PDF created"), name)
                        yield msg
            else:
                yield _("Creating a single pdf")
                # Remove the first and store it in a variable
                first = image_handles[0]
                image_handles.pop(0)
                # Save the first image as pdf and append the others
                name = os.path.join(self.dest, "%i.pdf" % self.counter)
                while os.path.isfile(name):
                    self.counter += 1
                    name = os.path.join(self.dest, "%i.pdf" % self.counter)
                first.save(name, "PDF", resolution=90.0, save_all=True,
                           append_images=image_handles)
