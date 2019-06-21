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
        self.resize = 10
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
    def preprocess_all(self):
        if not self.save_files and not self.m_pdf:
            yield _("Nothing to do, neither save files or make pdf is selected")
        else:
            if self.file_number >= 600 and self.save_files:
                yield _("Found too many files to copy, this is not implemented yet")
            else:
                for line in self.gather_images():
                    yield line

    # TODO: the images do not need to be copied neither saved if the user only wants a pdf
    def gather_images(self):
        known_extensions = ["JPG", "PNG"]
        yield _("Starting image gathering") + "\n"
        yield "%s: %i\n" % (_("Files Found"), self.file_number)
        for root, __, files in os.walk(self.source, topdown=False):
            if self.stop_running:
                yield _("Converter is stoppping")
                break
            for file in files:
                if self.stop_running:
                    break
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
                    if self.stop_running:
                        break
                    if self.deskew:
                        try:
                            self.deskew_image(source_path, destination_dir, file)
                            # continue because the image handle
                            # is already in the list
                            # and if save is true
                            # it is already saved in the output dir
                            continue
                        except (Exception, TesseractNotFoundError) as e:
                            self.stop_running = True
                            msg = "%s: %s" % (_("Error occurred while deskewing image"), e)
                            yield msg
                    else:
                        self.image_paths.append(source_path)
                    # Check destination and copy files over
                    if self.save_files:
                        if not os.path.exists(destination_dir):
                            os.mkdir(destination_dir)
                        file_name = str(file) + "." + extension.lower()
                        destination_file = os.path.join(destination_dir, file_name)
                        if not os.path.exists(destination_file):
                            shutil.copy2(source_path, destination_file)
        yield _("Gathering done")

    # BUG: Some images get flipped sideways
    # TODO: this is slow probably because of either opening the images,
    # or processing them trough tesseract
    def deskew_image(self, source_path, dest, file):
        dest_path = os.path.join(dest, file)
        img = Image.open(source_path)
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
        img.close()

    def check_handles(self):
        image_handles = [Image.open(image) for image in self.image_paths]
        PIL_handles = None
        if len(self.images) > 0:
            PIL_handles = [Image.open(image) for image in self.images]
        if PIL_handles is not None:
            image_handles += PIL_handles
        if len(image_handles) == 0:
            return False
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
                yield "%s %i" % (_("Creating multiple PDFs splitting by:"), sa)
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
