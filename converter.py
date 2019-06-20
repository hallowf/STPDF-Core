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
        self.make_pdf = kwargs.get("make_pdf", True)
        self.save_files = kwargs.get("save_files", False)
        self.image_paths = []
        self.images = []
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
        if self.installed_lang is None:
            gettext.install("stpdf-core")
        else:
            self.installed_lang.install()
        self.mute_other_loggers()

    def mute_other_loggers(self):
        logging.getLogger("PIL").setLevel(logging.ERROR)

    # checks how many files are there to copy over
    def preprocess_all(self):
        if not self.save_files and not self.make_pdf:
            yield _("Nothing to do, neither save files or make pdf is selected")
        else:
            if self.file_number >= 600 and self.save_files:
                yield _("Found too many files to copy, this is not implemented yet")
            else:
                for line in self.process_images():
                    yield line

    # TODO: the images do not need to be copied neither saved if the user only wants a pdf
    def process_images(self):
        known_extensions = ["JPG", "PNG"]
        yield _("Starting image processing")
        yield "%s: %i\n" % (_("Files Found"), self.file_number)
        for root, __, files in os.walk(self.source, topdown=False):
            if self.stop_running:
                yield _("Converter is stoppping")
                break
            for file in files:
                if self.stop_running:
                    break
                self.file_counter += 1
                if(round(self.file_counter % self.one_percent_files, 1) == 0.1):
                    msg = "%s / %s %s.\n" % (str(self.file_counter),
                                             str(self.file_number),
                                             _("processed"))
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
                            raise e
                    else:
                        self.image_paths.append(source_path)
                    # Check destination and copy files over
                    if self.save_files:
                        if not os.path.exists(destination_dir):
                            os.mkdir(destination_dir)
                        else:
                            file_name = str(file) + "." + extension.lower()

                        destination_file = os.path.join(destination_dir, file_name)
                        if not os.path.exists(destination_file):
                            shutil.copy2(source_path, destination_file)
        yield "Processing done"

    # BUG: Some images get flipped sideways
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
        print("image", img)
        if self.save_files:
            self.image_paths.append(source_path)
            img.save(dest_path)
        else:
            img.close()
            self.images.append(img)

    # Function to generate pdf's
    def make_pdf(self):
        image_handles = None
        # Get all image handles
        if not self.save_files:
            image_handles = [Image.open(image) for image in self.images]
        else:
            image_handles = [Image.open(image) for image in self.image_paths]
        if len(image_handles) == 0:
            yield _("Failed to obtain image handles something went wrong")
        else:
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
