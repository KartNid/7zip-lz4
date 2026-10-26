// Extract.cpp

#include "StdAfx.h"

#include "../../../Common/StringConvert.h"

#include "../../../Windows/FileDir.h"
#include "../../../Windows/FileName.h"
#include "../../../Windows/ErrorMsg.h"
#include "../../../Windows/PropVariant.h"
#include "../../../Windows/PropVariantConv.h"

#include "../Common/ExtractingFilePath.h"
#include "../Common/HashCalc.h"

#include "Extract.h"
#include "SetProperties.h"

using namespace NWindows;
using namespace NFile;
using namespace NDir;


static void SetErrorMessage(const char *message,
    const FString &path, HRESULT errorCode,
    UString &s)
{
  s = message;
  s += " : ";
  s += NError::MyFormatMessage(errorCode);
  s += " : ";
  s += fs2us(path);
}

// Decode a single compression stream to a temporary file so a large TAR can
// be inspected and extracted with normal seekable archive handling. The outer
// frame must finish successfully (including its checksum) before any output.
Z7_CLASS_IMP_COM_1(CSmartStreamCallback, IArchiveExtractCallback)
  Z7_IFACE_COM7_IMP(IProgress)
public:
  CMyComPtr<ISequentialOutStream> Stream;
  IFolderArchiveExtractCallback *Progress;
  Int32 OperationResult;
  bool Finished;
};

Z7_COM7F_IMF(CSmartStreamCallback::SetTotal(UInt64 /* size */))
{
  return S_OK;
}

Z7_COM7F_IMF(CSmartStreamCallback::SetCompleted(const UInt64 * /* value */))
{
  return Progress->SetCompleted(NULL);
}

Z7_COM7F_IMF(CSmartStreamCallback::GetStream(UInt32 index,
    ISequentialOutStream **stream, Int32 askMode))
{
  *stream = NULL;
  if (index != 0 || askMode != NArchive::NExtract::NAskMode::kExtract)
    return E_INVALIDARG;
  *stream = Stream;
  (*stream)->AddRef();
  return S_OK;
}

Z7_COM7F_IMF(CSmartStreamCallback::PrepareOperation(Int32 /* askMode */))
{
  return S_OK;
}

Z7_COM7F_IMF(CSmartStreamCallback::SetOperationResult(Int32 result))
{
  OperationResult = result;
  Finished = true;
  return S_OK;
}

static bool Smart_IsCompressionStream(const CCodecs *codecs, const CArc &arc)
{
  if (arc.FormatIndex < 0)
    return false;
  const UString &name = codecs->Formats[(unsigned)arc.FormatIndex].Name;
  return name.IsEqualTo_Ascii_NoCase("gzip")
      || name.IsEqualTo_Ascii_NoCase("bzip2")
      || name.IsEqualTo_Ascii_NoCase("xz")
      || name.IsEqualTo_Ascii_NoCase("lz4")
      || name.IsEqualTo_Ascii_NoCase("zstd")
      || name.IsEqualTo_Ascii_NoCase("lzma")
      || name.IsEqualTo_Ascii_NoCase("Z");
}

static HRESULT Smart_OpenTar(CCodecs *codecs, CArchiveLink &outer,
    const CExtractOptions &options, IOpenCallbackUI *openCallback,
    IFolderArchiveExtractCallback *progress, CTempFile &temp,
    CArchiveLink &tar, bool &isTar)
{
  isTar = false;
  const CArc &arc = outer.Arcs.Front();
  if (!Smart_IsCompressionStream(codecs, arc))
    return S_OK;
  UInt32 count;
  RINOK(arc.Archive->GetNumberOfItems(&count))
  if (count != 1)
    return S_OK;

  CMyComPtr2_Create<IOutStream, COutFileStream> out;
  out->ProcessedSize = 0;
  if (!temp.CreateRandomInTempFolder(FTEXT("7z-smart-"), &out->File))
    return GetLastError_noZero_HRESULT();
  CMyComPtr2_Create<IArchiveExtractCallback, CSmartStreamCallback> cb;
  cb->Stream = out.Interface();
  cb->Progress = progress;
  cb->OperationResult = NArchive::NExtract::NOperationResult::kDataError;
  cb->Finished = false;
  const UInt32 index = 0;
  const HRESULT res = arc.Archive->Extract(&index, 1, 0, cb);
  cb->Stream.Release();
  const HRESULT closeRes = out->Close();
  RINOK(res)
  RINOK(closeRes)
  if (!cb->Finished || cb->OperationResult != NArchive::NExtract::NOperationResult::kOK)
  {
    RINOK(progress->SetOperationResult(cb->OperationResult, false))
    return E_FAIL;
  }

  const int format = codecs->FindFormatForArchiveType(UString("tar"));
  if (format < 0)
    return S_OK;
  CObjectVector<COpenType> types;
  COpenType type;
  type.FormatIndex = format;
  type.Recursive = false;
  types.Add(type);
  CIntVector excluded;
  COpenOptions op;
  op.codecs = codecs;
  op.types = &types;
  op.excludedFormats = &excluded;
  op.filePath = fs2us(temp.GetPath());
  #ifndef Z7_SFX
  op.props = &options.Properties;
  #else
  UNUSED_VAR(options)
  #endif
  const HRESULT openRes = tar.Open_Strict(op, openCallback);
  if (openRes == S_FALSE)
  {
    UString name;
    RINOK(arc.GetItem_Path(0, name))
    if (name.Len() >= 4 && StringsAreEqualNoCase_Ascii(name.RightPtr(4), ".tar"))
      return E_FAIL; // An explicitly named TAR must not silently become a file.
    return S_OK; // A normal single-file compression stream, not a TAR.
  }
  RINOK(openRes)
  isTar = true;
  return S_OK;
}

static UString Smart_ArchiveName(const UString &path, bool compressedTar)
{
  UString name = path.Ptr((unsigned)(path.ReverseFind_PathSepar() + 1));
  int dot = name.ReverseFind(L'.');
  if (dot > 0)
    name.DeleteFrom((unsigned)dot);
  if (compressedTar && name.Len() > 4
      && StringsAreEqualNoCase_Ascii(name.RightPtr(4), ".tar"))
    name.DeleteFrom(name.Len() - 4);
  return Get_Correct_FsFile_Name(name);
}

static bool Smart_IsRealDir(const FString &path)
{
  NFind::CFileInfo info;
  return info.Find(path) && info.IsDir() && !info.IsOsSymLink();
}

static HRESULT Smart_OutputDir(const CArc &arc, const CRecordVector<UInt32> &indices,
    const UString &archiveName, FString &dir)
{
  bool oneFolder = true;
  UString root;
  FOR_VECTOR (i, indices)
  {
    CReadArcItem item;
    RINOK(arc.GetItem(indices[i], item))
    unsigned first = 0;
    while (first < item.PathParts.Size() && item.PathParts[first] == L".")
      first++;
    if (first == item.PathParts.Size() && item.IsDir)
      continue; // TAR's optional './' root entry is not a second folder.
    if (first == item.PathParts.Size() || item.PathParts[first].IsEmpty()
        || item.PathParts[first] == L".."
        || (first + 1 == item.PathParts.Size() && !item.IsDir))
    {
      oneFolder = false;
      break;
    }
    if (root.IsEmpty())
      root = item.PathParts[first];
    else if (root != item.PathParts[first])
    {
      oneFolder = false;
      break;
    }
  }
  if (dir.IsEmpty())
    dir = FTEXT(".");
  if (!CreateComplexDir(dir))
    return GetLastError_noZero_HRESULT();
  NName::NormalizeDirPathPrefix(dir);
  const FString prefix = dir;
  if (oneFolder && !root.IsEmpty())
  {
    const FString folder = prefix + us2fs(Get_Correct_FsFile_Name(root));
    // Merge ordinary directories. Links and same-name files still need a container.
    if (Smart_IsRealDir(folder) || CreateDir(folder))
      return S_OK;
    if (!NFind::DoesFileOrDirExist(folder))
      return GetLastError_noZero_HRESULT();
  }
  // Reuse an ordinary archive-name folder; number collisions with files or links.
  for (UInt32 number = 1; number != 0; number++)
  {
    UString name = archiveName;
    if (number != 1)
    {
      name += " (";
      name.Add_UInt32(number);
      name.Add_Char(')');
    }
    const FString candidate = prefix + us2fs(name);
    if (Smart_IsRealDir(candidate) || CreateDir(candidate))
    {
      dir = candidate;
      NName::NormalizeDirPathPrefix(dir);
      return S_OK;
    }
    if (!NFind::DoesFileOrDirExist(candidate))
      return GetLastError_noZero_HRESULT();
  }
  return E_FAIL;
}


static HRESULT DecompressArchive(
    CCodecs *codecs,
    const CArchiveLink &arcLink,
    UInt64 packSize,
    const NWildcard::CCensorNode &wildcardCensor,
    const CExtractOptions &options,
    const UString &smartName,
    bool calcCrc,
    IExtractCallbackUI *callback,
    IFolderArchiveExtractCallback *callbackFAE,
    CArchiveExtractCallback *ecs,
    UString &errorMessage,
    UInt64 &stdInProcessed)
{
  const CArc &arc = arcLink.Arcs.Back();
  stdInProcessed = 0;
  IInArchive *archive = arc.Archive;
  CRecordVector<UInt32> realIndices;
  
  UStringVector removePathParts;

  FString outDir = options.OutputDir;
  if (!options.SmartExtract && options.OutDirMode != NExtractOutDirMode::k_Direct)
  {
    UString replaceName = arc.DefaultName;
    if (arcLink.Arcs.Size() > 1)
    {
      // Most "pe" archives have same name of archive subfile "[0]" or ".rsrc_1".
      // So it extracts different archives to one folder.
      // We will use top level archive name
      const CArc &arc0 = arcLink.Arcs[0];
      if (arc0.FormatIndex >= 0 && StringsAreEqualNoCase_Ascii(codecs->Formats[(unsigned)arc0.FormatIndex].Name, "pe"))
        replaceName = arc0.DefaultName;
    }
    const FString correctedName = us2fs(Get_Correct_FsFile_Name(replaceName));
    if (options.OutDirMode == NExtractOutDirMode::k_AddArcName)
    {
      outDir += correctedName;
      NFile::NName::NormalizeDirPathPrefix(outDir);
    }
    else // eo.OutDirMode == NExtractOutDirMode::k_ReplaceAsterisk;
      outDir.Replace(FString("*"), correctedName);
  }

  bool elimIsPossible = false;
  UString elimPrefix; // only pure name without dir delimiter
  FString outDirReduced = outDir;
  
  if (!options.SmartExtract && options.ElimDup.Val && options.PathMode != NExtract::NPathMode::kAbsPaths)
  {
    UString dirPrefix;
    SplitPathToParts_Smart(fs2us(outDir), dirPrefix, elimPrefix);
    if (!elimPrefix.IsEmpty())
    {
      if (IsPathSepar(elimPrefix.Back()))
        elimPrefix.DeleteBack();
      if (!elimPrefix.IsEmpty())
      {
        outDirReduced = us2fs(dirPrefix);
        elimIsPossible = true;
      }
    }
  }

  const bool allFilesAreAllowed = wildcardCensor.AreAllAllowed();

  if (!options.StdInMode)
  {
    UInt32 numItems;
    RINOK(archive->GetNumberOfItems(&numItems))
    
    CReadArcItem item;

    for (UInt32 i = 0; i < numItems; i++)
    {
      if (elimIsPossible
          || !allFilesAreAllowed
          || options.ExcludeDirItems
          || options.ExcludeFileItems)
      {
        RINOK(arc.GetItem(i, item))
        if (item.IsDir ? options.ExcludeDirItems : options.ExcludeFileItems)
          continue;
      }
      else
      {
        #ifdef SUPPORT_ALT_STREAMS
        item.IsAltStream = false;
        if (!options.NtOptions.AltStreams.Val && arc.Ask_AltStream)
        {
          RINOK(Archive_IsItem_AltStream(arc.Archive, i, item.IsAltStream))
        }
        #endif
      }

      #ifdef SUPPORT_ALT_STREAMS
      if (!options.NtOptions.AltStreams.Val && item.IsAltStream)
        continue;
      #endif
      
      if (elimIsPossible)
      {
        const UString &s =
          #ifdef SUPPORT_ALT_STREAMS
            item.MainPath;
          #else
            item.Path;
          #endif
        if (!IsPath1PrefixedByPath2(s, elimPrefix))
          elimIsPossible = false;
        else
        {
          wchar_t c = s[elimPrefix.Len()];
          if (c == 0)
          {
            if (!item.MainIsDir)
              elimIsPossible = false;
          }
          else if (!IsPathSepar(c))
            elimIsPossible = false;
        }
      }

      if (!allFilesAreAllowed)
      {
        if (!CensorNode_CheckPath(wildcardCensor, item))
          continue;
      }

#if 1 // 1 : v24.06 : to exclude AUX items from processing
      if (arc.Ask_Aux)
      {
        bool isAux;
        RINOK(Archive_IsItem_Aux(archive, i, isAux))
        if (isAux)
          continue;
      }
#endif

      realIndices.Add(i);
    }
    
    if (realIndices.Size() == 0)
    {
      callback->ThereAreNoFiles();
      return callback->ExtractResult(S_OK);
    }
  }

  if (options.SmartExtract)
    RINOK(Smart_OutputDir(arc, realIndices, smartName, outDir))

  if (elimIsPossible)
  {
    removePathParts.Add(elimPrefix);
    // outDir = outDirReduced;
  }

  #ifdef _WIN32
  // GetCorrectFullFsPath doesn't like "..".
  // outDir.TrimRight();
  // outDir = GetCorrectFullFsPath(outDir);
  #endif

  if (outDir.IsEmpty())
    outDir = "." STRING_PATH_SEPARATOR;
  /*
  #ifdef _WIN32
  else if (NName::IsAltPathPrefix(outDir)) {}
  #endif
  */
  else if (!CreateComplexDir(outDir))
  {
    const HRESULT res = GetLastError_noZero_HRESULT();
    SetErrorMessage("Cannot create output directory", outDir, res, errorMessage);
    return res;
  }

  ecs->Init(
      options.NtOptions,
      options.StdInMode ? &wildcardCensor : NULL,
      &arc,
      callbackFAE,
      options.StdOutMode, options.TestMode,
      outDir,
      removePathParts, false,
      packSize);

  ecs->Is_elimPrefix_Mode = elimIsPossible;
  ecs->SmartExtract = options.SmartExtract;

  
  #ifdef SUPPORT_LINKS
  
  if (!options.StdInMode &&
      !options.TestMode &&
      options.NtOptions.HardLinks.Val)
  {
    RINOK(ecs->PrepareHardLinks(&realIndices))
  }
    
  #endif

  
  HRESULT result;
  const Int32 testMode = (options.TestMode && !calcCrc) ? 1: 0;

  CArchiveExtractCallback_Closer ecsCloser(ecs);

  if (options.StdInMode)
  {
    result = archive->Extract(NULL, (UInt32)(Int32)-1, testMode, ecs);
    NCOM::CPropVariant prop;
    if (archive->GetArchiveProperty(kpidPhySize, &prop) == S_OK)
      ConvertPropVariantToUInt64(prop, stdInProcessed);
  }
  else
  {
    // v23.02: we reset completed value that could be set by Open() operation
    IArchiveExtractCallback *aec = ecs;
    const UInt64 val = 0;
    RINOK(aec->SetCompleted(&val))
    result = archive->Extract(realIndices.ConstData(), realIndices.Size(), testMode, aec);
  }
  
  const HRESULT res2 = ecsCloser.Close();
  if (result == S_OK)
    result = res2;

  return callback->ExtractResult(result);
}

/* v9.31: BUG was fixed:
   Sorted list for file paths was sorted with case insensitive compare function.
   But FindInSorted function did binary search via case sensitive compare function */

int Find_FileName_InSortedVector(const UStringVector &fileNames, const UString &name);
int Find_FileName_InSortedVector(const UStringVector &fileNames, const UString &name)
{
  unsigned left = 0, right = fileNames.Size();
  while (left != right)
  {
    const unsigned mid = (unsigned)(((size_t)left + (size_t)right) / 2);
    const UString &midVal = fileNames[mid];
    const int comp = CompareFileNames(name, midVal);
    if (comp == 0)
      return (int)mid;
    if (comp < 0)
      right = mid;
    else
      left = mid + 1;
  }
  return -1;
}



HRESULT Extract(
    // DECL_EXTERNAL_CODECS_LOC_VARS
    CCodecs *codecs,
    const CObjectVector<COpenType> &types,
    const CIntVector &excludedFormats,
    UStringVector &arcPaths, UStringVector &arcPathsFull,
    const NWildcard::CCensorNode &wildcardCensor,
    const CExtractOptions &options,
    IOpenCallbackUI *openCallback,
    IExtractCallbackUI *extractCallback,
    IFolderArchiveExtractCallback *faeCallback,
    #ifndef Z7_SFX
    IHashCalc *hash,
    #endif
    UString &errorMessage,
    CDecompressStat &st)
{
  st.Clear();
  if (options.SmartExtract && (options.StdInMode || options.StdOutMode
      || options.TestMode || options.PathMode != NExtract::NPathMode::kFullPaths))
  {
    errorMessage = "Smart extraction requires file input and full-path extraction (x).";
    return E_INVALIDARG;
  }
  UInt64 totalPackSize = 0;
  CRecordVector<UInt64> arcSizes;

  unsigned numArcs = options.StdInMode ? 1 : arcPaths.Size();

  unsigned i;
  
  for (i = 0; i < numArcs; i++)
  {
    NFind::CFileInfo fi;
    fi.Size = 0;
    if (!options.StdInMode)
    {
      const FString arcPath = us2fs(arcPaths[i]);
      if (!fi.Find_FollowLink(arcPath))
      {
        const HRESULT errorCode = GetLastError_noZero_HRESULT();
        SetErrorMessage("Cannot find archive file", arcPath, errorCode, errorMessage);
        return errorCode;
      }
      if (fi.IsDir())
      {
        HRESULT errorCode = E_FAIL;
        SetErrorMessage("The item is a directory", arcPath, errorCode, errorMessage);
        return errorCode;
      }
    }
    arcSizes.Add(fi.Size);
    totalPackSize += fi.Size;
  }

  CBoolArr skipArcs(numArcs);
  for (i = 0; i < numArcs; i++)
    skipArcs[i] = false;

  CArchiveExtractCallback *ecs = new CArchiveExtractCallback;
  CMyComPtr<IArchiveExtractCallback> ec(ecs);
  
  const bool multi = (numArcs > 1);
  
  ecs->InitForMulti(multi,
      options.PathMode,
      options.OverwriteMode,
      options.ZoneMode,
      false // keepEmptyDirParts
      );
  #ifndef Z7_SFX
  ecs->SetHashMethods(hash);
  #endif

  if (multi)
  {
    RINOK(faeCallback->SetTotal(totalPackSize))
  }

  UInt64 totalPackProcessed = 0;
  bool thereAreNotOpenArcs = false;
  
  for (i = 0; i < numArcs; i++)
  {
    if (skipArcs[i])
      continue;

    ecs->InitBeforeNewArchive();

    const UString &arcPath = arcPaths[i];
    NFind::CFileInfo fi;
    if (options.StdInMode)
    {
      // do we need ctime and mtime?
      // fi.ClearBase();
      // fi.Size = 0; // (UInt64)(Int64)-1;
      if (!fi.SetAs_StdInFile())
        return GetLastError_noZero_HRESULT();
    }
    else
    {
      if (!fi.Find_FollowLink(us2fs(arcPath)) || fi.IsDir())
      {
        const HRESULT errorCode = GetLastError_noZero_HRESULT();
        SetErrorMessage("Cannot find archive file", us2fs(arcPath), errorCode, errorMessage);
        return errorCode;
      }
    }

    /*
    #ifndef Z7_NO_CRYPTO
    openCallback->Open_Clear_PasswordWasAsked_Flag();
    #endif
    */

    RINOK(extractCallback->BeforeOpen(arcPath, options.TestMode))
    CArchiveLink arcLink;

    CObjectVector<COpenType> types2 = types;
    /*
    #ifndef Z7_SFX
    if (types.IsEmpty())
    {
      int pos = arcPath.ReverseFind(L'.');
      if (pos >= 0)
      {
        UString s = arcPath.Ptr(pos + 1);
        int index = codecs->FindFormatForExtension(s);
        if (index >= 0 && s.IsEqualTo("001"))
        {
          s = arcPath.Left(pos);
          pos = s.ReverseFind(L'.');
          if (pos >= 0)
          {
            int index2 = codecs->FindFormatForExtension(s.Ptr(pos + 1));
            if (index2 >= 0) // && s.CompareNoCase(L"rar") != 0
            {
              types2.Add(index2);
              types2.Add(index);
            }
          }
        }
      }
    }
    #endif
    */

    COpenOptions op;
    #ifndef Z7_SFX
    op.props = &options.Properties;
    #endif
    op.codecs = codecs;
    op.types = &types2;
    op.excludedFormats = &excludedFormats;
    op.stdInMode = options.StdInMode;
    op.stream = NULL;
    op.filePath = arcPath;

    HRESULT result = arcLink.Open_Strict(op, openCallback);

    if (result == E_ABORT)
      return result;

    // arcLink.Set_ErrorsText();
    RINOK(extractCallback->OpenResult(codecs, arcLink, arcPath, result))

    if (result != S_OK)
    {
      thereAreNotOpenArcs = true;
      if (!options.StdInMode)
        totalPackProcessed += fi.Size;
      continue;
    }

   #if defined(_WIN32) && !defined(UNDER_CE) && !defined(Z7_SFX)
    if (options.ZoneMode != NExtract::NZoneIdMode::kNone
        && !options.StdInMode)
    {
      ReadZoneFile_Of_BaseFile(us2fs(arcPath), ecs->ZoneBuf);
    }
   #endif
    

    if (arcLink.Arcs.Size() != 0)
    {
      if (arcLink.GetArc()->IsHashHandler(op))
      {
        if (!options.TestMode)
        {
          /* real Extracting to files is possible.
             But user can think that hash archive contains real files.
             So we block extracting here. */
          // v23.00 : we don't break process.
          RINOK(extractCallback->OpenResult(codecs, arcLink, arcPath, E_NOTIMPL))
          thereAreNotOpenArcs = true;
          if (!options.StdInMode)
            totalPackProcessed += fi.Size;
          continue;
          // return E_NOTIMPL; // before v23
        }
        FString dirPrefix = us2fs(options.HashDir);
        if (dirPrefix.IsEmpty())
        {
          if (!NFile::NDir::GetOnlyDirPrefix(us2fs(arcPath), dirPrefix))
          {
            // return GetLastError_noZero_HRESULT();
          }
        }
        if (!dirPrefix.IsEmpty())
          NName::NormalizeDirPathPrefix(dirPrefix);
        ecs->DirPathPrefix_for_HashFiles = dirPrefix;
      }
    }

    if (!options.StdInMode)
    {
      // numVolumes += arcLink.VolumePaths.Size();
      // arcLink.VolumesSize;

      // totalPackSize -= DeleteUsedFileNamesFromList(arcLink, i + 1, arcPaths, arcPathsFull, &arcSizes);
      // numArcs = arcPaths.Size();
      if (arcLink.VolumePaths.Size() != 0)
      {
        Int64 correctionSize = (Int64)arcLink.VolumesSize;
        FOR_VECTOR (v, arcLink.VolumePaths)
        {
          int index = Find_FileName_InSortedVector(arcPathsFull, arcLink.VolumePaths[v]);
          if (index >= 0)
          {
            if ((unsigned)index > i)
            {
              skipArcs[(unsigned)index] = true;
              correctionSize -= arcSizes[(unsigned)index];
            }
          }
        }
        if (correctionSize != 0)
        {
          Int64 newPackSize = (Int64)totalPackSize + correctionSize;
          if (newPackSize < 0)
            newPackSize = 0;
          totalPackSize = (UInt64)newPackSize;
          RINOK(faeCallback->SetTotal(totalPackSize))
        }
      }
    }

    /*
    // Now openCallback and extractCallback use same object. So we don't need to send password.

    #ifndef Z7_NO_CRYPTO
    bool passwordIsDefined;
    UString password;
    RINOK(openCallback->Open_GetPasswordIfAny(passwordIsDefined, password))
    if (passwordIsDefined)
    {
      RINOK(extractCallback->SetPassword(password))
    }
    #endif
    */

    CTempFile smartTemp;
    CArchiveLink smartTar;
    CArchiveLink *extractLink = &arcLink;
    bool compressedTar = false;
    if (options.SmartExtract)
    {
      const HRESULT smartRes = Smart_OpenTar(codecs, arcLink, options,
          openCallback, faeCallback, smartTemp, smartTar, compressedTar);
      if (smartRes != S_OK)
      {
        errorMessage = "Cannot completely decode compressed stream for smart extraction.";
        return smartRes;
      }
      if (compressedTar)
        extractLink = &smartTar;
    }
    CArc &arc = extractLink->Arcs.Back();
    arc.MTime.Def = !options.StdInMode
        #ifdef _WIN32
        && !fi.IsDevice
        #endif
        ;
    if (arc.MTime.Def)
      arc.MTime.Set_From_FiTime(fi.MTime);

    UInt64 packProcessed;
    const bool calcCrc =
        #ifndef Z7_SFX
          (hash != NULL);
        #else
          false;
        #endif

    RINOK(DecompressArchive(
        codecs,
        *extractLink,
        fi.Size + arcLink.VolumesSize,
        wildcardCensor,
        options,
        Smart_ArchiveName(arcPath, compressedTar),
        calcCrc,
        extractCallback, faeCallback, ecs,
        errorMessage, packProcessed))

    if (!options.StdInMode)
      packProcessed = fi.Size + arcLink.VolumesSize;
    totalPackProcessed += packProcessed;
    ecs->LocalProgressSpec->InSize += packProcessed;
    ecs->LocalProgressSpec->OutSize = ecs->UnpackSize;
    if (!errorMessage.IsEmpty())
      return E_FAIL;
  }

  if (multi || thereAreNotOpenArcs)
  {
    RINOK(faeCallback->SetTotal(totalPackSize))
    RINOK(faeCallback->SetCompleted(&totalPackProcessed))
  }

  st.NumFolders = ecs->NumFolders;
  st.NumFiles = ecs->NumFiles;
  st.NumAltStreams = ecs->NumAltStreams;
  st.UnpackSize = ecs->UnpackSize;
  st.AltStreams_UnpackSize = ecs->AltStreams_UnpackSize;
  st.NumArchives = arcPaths.Size();
  st.PackSize = ecs->LocalProgressSpec->InSize;
  return S_OK;
}
